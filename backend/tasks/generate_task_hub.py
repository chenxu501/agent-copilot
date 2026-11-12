# tasks/generate_task_hub.py —— 任务生成辅助：拼上下文提示词让 LLM 拆任务/补参数/判安全

# 导入 entity 包的 Tool 实体类（API 工具元数据定义，≈ domain.Tool）
from entity import Tool
# 导入 models/llm.py 的 LargeLanguageModel，调用大模型的客户端封装
from models import LargeLanguageModel
# 导入 prompt 包的提示词模板中心和工厂方法，负责拼装/解析提示词（≈ 模板引擎 + 策略模式）
from prompt import PromptModelHub, QwenModelPromptHub, create_prompt_hub
# 导入 tools/tool_manager.py 的 ToolManager，从 MongoDB 查工具列表（≈ DAO/Repository）
from tools import ToolManager
# 导入 utils 包的日志对象
from utils import logger
# 标准库：异常堆栈格式化，出错时把调用栈写进日志（≈ e.printStackTrace()）
import traceback


# 任务生成中心：所有"拼提示词→调 LLM→解析输出"的生成逻辑集中在这里（≈ 只依赖 LLM 的 Service）
class GenerateTaskHub:

    # 构造方法：初始化 LLM 客户端、提示词中心、工具管理器，并保存模型采样参数
    def __init__(self, model, temperature, top_p, api_url, api_key, mongo_host, mongo_db, mongo_port, milvus_uri, milvus_db_name):
        # 创建 models/llm.py 的 LargeLanguageModel 并持有，各生成方法都用它调 LLM
        self.LargeLanguageModel = LargeLanguageModel(api_url, api_key)
        # 按模型名创建提示词中心（工厂方法，≈ 工厂模式）
        self.PromptModelHub = create_prompt_hub(model)
        # 创建 tools/tool_manager.py 的 ToolManager 并持有，生成根任务提示词时取全部工具列表
        self.ToolManager = ToolManager(mongo_host, mongo_db, mongo_port, milvus_uri, milvus_db_name)
        # 保存模型名，调 LLM 时使用
        self.model = model
        # 保存采样温度，控制生成随机性
        self.temperature = temperature
        # 保存核采样概率 top_p，控制生成多样性
        self.top_p = top_p


    # 方法：判断用户提问是单任务还是多任务并生成根任务描述，返回 (是否单任务, 任务描述)
    def gen_root_task(self, query):
        # 调用 tools/tool_manager.py 的 ToolManager.get_raw_all_tools()，取全部工具让 LLM 知道有哪些 API 可用
        tools = self.ToolManager.get_raw_all_tools()
        # 调用 prompt 包的 PromptModelHub.gen_root_task_prompt()，拼出拆任务提示词
        prompt = self.PromptModelHub.gen_root_task_prompt(query, tools)
        # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让大模型把用户提问拆成任务
        task_description = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature, self.top_p)
        # 调用 prompt 包的 PromptModelHub.post_process_gen_root_task()，解析输出为 (是否单任务, 任务描述)
        isSingleTask, task_description = self.PromptModelHub.post_process_gen_root_task(task_description)
        # 返回单任务标记和根任务描述
        return isSingleTask, task_description


    # 方法：缺参数时生成"去查这个参数"的新查询语句
    def gen_param_task(self, query, params, missing_params):
        # 调用 prompt 包的 PromptModelHub.gen_param_task_prompt()，拼出补参查询提示词
        prompt = self.PromptModelHub.gen_param_task_prompt(query, params, missing_params)
        # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让 LLM 生成补参查询语句
        task_description = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature, self.top_p)
        # 返回生成的补参任务描述词
        return task_description


    # 方法：根据原始提问和已有 API 调用链生成下一个子任务，返回 (任务是否完成, 下一个子任务描述)
    def gen_from_context_task(self, query, apis):
        # 调用 prompt 包的 PromptModelHub.gen_subtask_context_prompt()，把原始需求和已调用 API 链拼进提示词
        prompt = self.PromptModelHub.gen_subtask_context_prompt(query, apis)
        # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让 LLM 判断是否还有后续任务
        task_description = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature, self.top_p)
        # 调用 prompt 包的 PromptModelHub.post_process_gen_subtask_task()，解析为 (任务是否完成, 子任务描述)
        flag, task_description = self.PromptModelHub.post_process_gen_subtask_task(task_description)
        # 打调试日志：记录任务完成标记和后续任务描述
        logger.debug(f"基于上下文生成子任务时检查：任务完成？{flag}；后续任务描述：{task_description}")
        # 返回完成标记和子任务描述
        return flag, task_description

    # 方法：根据上下文反推出"用户的诉求描述"（辅助方法）
    def gen_context_request_task(self, contexts):
        # 调用 prompt 包的 PromptModelHub.gen_context_request()，拼出反推用户诉求的提示词
        prompt = self.PromptModelHub.gen_context_request(contexts)
        # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让 LLM 反推用户诉求
        user_request = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature,
                                                                self.top_p)
        # 返回生成的用户诉求语句
        return user_request

    # 方法：安全校验，判断这次调用是否是提示注入攻击，返回 (是否攻击, 原因说明)
    def gen_judge_task(self, query, tool: Tool, requestBody: dict):
        # 该工具不需要做注入校验（如查询类接口）则直接放行
        if not tool.isValidate:
            # 返回 (False, None) 表示校验通过（≈ 返回 false, null）
            return False, None
        else:
            # 调用 prompt 包的 PromptModelHub.judge_validate()，拼出安全校验提示词
            prompt = self.PromptModelHub.judge_validate(query, tool, requestBody)
            # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让 LLM 当安全审核员
            judge_result = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature,
                                                                    self.top_p)
            # 调用 prompt 包的 PromptModelHub.post_process_gen_judge_task()，解析为 (是否攻击, 原因)
            flag, reason = self.PromptModelHub.post_process_gen_judge_task(judge_result)
            # 返回校验结果
            return flag, reason


# if __name__ == "__main__"：直接运行本文件时的本地测试（≈ Java 的 main 方法）
if __name__ == "__main__":
    # 第三方库 dotenv：从 .env 文件加载环境变量
    from dotenv import load_dotenv
    # 标准库 os：读环境变量（≈ System.getenv）
    import os
    # 加载 .env 里的环境变量配置
    load_dotenv()
    # 读 milvus_uri 环境变量，第二个参数是默认值（≈ getOrDefault）
    milvus_uri = os.getenv("milvus_uri", "http://localhost:19530")
    # 打日志：确认读到的 Milvus 地址
    logger.info(milvus_uri)
    # 读向量模型文件路径配置
    model_path = os.getenv("model_path", "model")
    # 读 Milvus 数据库名配置
    milvus_db_name = os.getenv("milvus_db_name", "tool_db")
    # 读大模型名称配置
    model = os.getenv("model", "qwen-max-0919")
    # 读采样温度并转 float
    temperature = float(os.getenv("temperature", "0.01"))
    # 读核采样概率并转 float
    top_p = float(os.getenv("top_p", "0.01"))
    # 读 MongoDB 主机地址
    mongo_host = os.getenv("mongo_host", "127.0.0.1")
    # 读 MongoDB 数据库名
    mongo_db = os.getenv("mongo_db", "tools")
    # 读 MongoDB 端口并转 int
    mongo_port = int(os.getenv("mongo_port", "27017"))
    # 读检索数量 topK 并转 int
    topK = int(os.getenv("topK", "5"))
    # 读大模型 API Key
    api_key = os.getenv("api_key", "")
    # 读大模型接口地址
    base_url = os.getenv("base_url", "")
    # 创建 tools/tool_manager.py 的 ToolManager 实例，后面按 id 取测试用工具
    toolManager = ToolManager('localhost', "tools", 27017, milvus_uri, milvus_db_name)
    # 创建本类实例，准备做提示注入校验测试
    generateTaskHub = GenerateTaskHub(model, temperature, top_p, base_url, api_key)

    # 调用 tools/tool_manager.py 的 ToolManager.get_tools_by_ids()，按 id 取工具并拿第一个做测试
    tool = toolManager.get_tools_by_ids([15])[0]
    # 调用本类 gen_judge_task()，测试"数量为 10"的正常创建订单请求能否通过安全校验
    x1, reason1 = generateTaskHub.gen_judge_task("请创建一个订单，该订单的产品ID为1，数量为10，供应商Id为1,配送区域为北京的订单", tool,
                                                 {"quantity": 10, "supplierId": 1, "productId": 1, "orderRegion": "北京"})

    # 调用本类 gen_judge_task()，测试"数量为 -10"的非法参数请求会不会被判为攻击
    x2, reason2 = generateTaskHub.gen_judge_task("请创建一个订单，该订单的产品ID为1，数量为-10，供应商Id为1,配送区域为北京的订单", tool,
                                                 {"quantity": -10, "supplierId": 1, "productId": 1, "orderRegion": "北京"})


    # 调用本类 gen_judge_task()，测试配送区域为空字符串的请求校验结果
    x3, reason3 = generateTaskHub.gen_judge_task("请创建一个订单，该订单的产品ID为1，数量为10，供应商Id为1,配送区域为北京的订单", tool,
                                                 {"quantity": 10, "supplierId": 1, "productId": 1, "orderRegion": ""})


    # 调用本类 gen_judge_task()，测试缺少配送区域字段的请求校验结果
    x4, reason4 = generateTaskHub.gen_judge_task("请创建一个订单，该订单的产品ID为1，数量为10，供应商Id为1,配送区域为北京的订单", tool,
                                                 {"quantity": 10, "supplierId": 1, "productId": 1})
