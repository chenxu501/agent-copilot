# api_selection_hub.py —— 两步法选工具：Milvus 向量粗筛 → LLM 细选出本次要用的 API 工具

# 导入 customize_milvus_wrapper/customize_milvus.py 的 CustomizeMilvus，做 Milvus 向量语义检索
from customize_milvus_wrapper import CustomizeMilvus
# 导入 models 包的 LargeLanguageModel（LLM 客户端）和 RemoteEmbeddingModel（远程向量模型）
from models import LargeLanguageModel, RemoteEmbeddingModel
# 导入 prompt 包的提示词模板中心和工厂方法，负责拼装/解析选工具提示词（≈ 模板引擎 + 策略模式）
from prompt import PromptModelHub, QwenModelPromptHub, create_prompt_hub
# 导入 tools/tool_manager.py 的 ToolManager，从 MongoDB/缓存取工具详情（≈ DAO/Repository）
from tools import ToolManager
# 导入 utils 包的日志对象
from utils import logger
# 标准库：异常堆栈格式化，出错时把调用栈写进日志（≈ e.printStackTrace()）
import traceback


# 工具选型中心：三步漏斗——向量粗筛 → reranker 精排 → LLM 最终裁决（≈ 策略筛选 Service）
class ApiSelectionHub:

    # 构造方法：初始化向量库客户端、LLM 客户端、提示词中心和工具管理器（≈ 构造方法注入依赖）
    def __init__(self, milvus_uri, model_path, milvus_db_name, model, temperature, top_p,
            mongo_host, mongo_db, mongo_port, api_url, api_key):
        # 创建 customize_milvus_wrapper/customize_milvus.py 的 CustomizeMilvus 并持有，后面做向量语义检索
        self.milvus = CustomizeMilvus(milvus_uri, milvus_db_name)
        # 创建 models/llm.py 的 LargeLanguageModel 并持有，后面让 LLM 裁决最终工具
        self.LargeLanguageModel = LargeLanguageModel(api_url, api_key)
        # 按模型名创建对应提示词中心（工厂方法，≈ 工厂模式）
        self.PromptModelHub = create_prompt_hub(model)
        # 创建 tools/tool_manager.py 的 ToolManager 并持有，后面按 id 查工具、做重排检索
        self.ToolManager = ToolManager(mongo_host, mongo_db, mongo_port, milvus_uri, milvus_db_name)
        # 保存模型名，调 LLM 时使用
        self.model = model
        # 保存采样温度，控制生成随机性
        self.temperature = temperature
        # 保存核采样概率 top_p，控制生成多样性
        self.top_p = top_p

    # 方法：给定用户查询做"粗筛+细选"，挑出唯一最匹配的 API 工具，失败返回 None
    def get_tool_coarse_and_fine(self, query, required_argument, topK):
        # 用 try 包住全流程，任何异常都兜底返回 None（try/except ≈ try/catch）
        try:
            # 调用 customize_milvus_wrapper/customize_milvus.py 的 CustomizeMilvus.get_docs()，向量检索召回 topK*2 个候选工具 id
            tool_ids = self.milvus.get_docs("tools", query, topK * 2)
            # 调用 tools/tool_manager.py 的 ToolManager.get_tools_by_ids()，按 id 批量查工具详情（MongoDB+缓存）
            vector_search_tools = self.ToolManager.get_tools_by_ids(tool_ids)

            # 打日志：记录向量检索的查询词
            logger.info(f"[向量检索] 查询: {query}")
            # 打日志：记录粗筛召回的候选工具数量
            logger.info(f"[向量检索] 候选工具数量: {len(vector_search_tools)}")
            # 遍历打印每个候选工具（enumerate 同时拿下标和元素）
            for i, tool in enumerate(vector_search_tools):
                # 打调试日志：候选工具的 id、接口名和中文名
                logger.debug(f"[向量检索] 工具 {i+1}: [{tool.tool_id}] {tool.operationId}-{tool.name_for_human}")

            # 调用 tools/tool_manager.py 的 ToolManager.search_tools_with_rerank()，向量召回后用重排序模型精排取前 topK 个
            reranked_tools = self.ToolManager.search_tools_with_rerank(query, top_k=topK * 2, final_top_n=topK)

            # 打日志：记录重排检索的查询词
            logger.info(f"[重排序] 查询: {query}")
            # 打日志：记录重排后的工具数量
            logger.info(f"[重排序] 重排序后工具数量: {len(reranked_tools)}")
            # 遍历打印重排后的每个工具
            for i, tool in enumerate(reranked_tools):
                # 打调试日志：重排后工具的 id、接口名和中文名
                logger.debug(f"[重排序] 工具 {i+1}: [{tool.tool_id}] {tool.operationId}-{tool.name_for_human}")

            # 不带必需参数约束的普通选工具流程
            if required_argument is None:
                # 优先用重排结果，重排为空则退回向量粗筛结果（三元表达式 ≈ 三目运算符）
                tools = reranked_tools if reranked_tools else vector_search_tools
                # 调用 prompt 包的 PromptModelHub.gen_tool_selection_prompt()，生成"选工具"提示词
                prompt = self.PromptModelHub.gen_tool_selection_prompt(query, tools)
                # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让 LLM 裁决唯一最匹配的工具
                model_output = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature, self.top_p)
                # 调用 prompt 包的 PromptModelHub.post_process_tool_selection_result()，从 LLM 输出解析出工具对象
                final_tool = self.PromptModelHub.post_process_tool_selection_result(model_output, tools)
            else:
                # 带"必需参数"约束的选工具流程（同样优先用重排结果）
                tools = reranked_tools if reranked_tools else vector_search_tools
                # 调用 prompt 包的 PromptModelHub.gen_required_argument_tool_selection_prompt()，生成带必需参数约束的提示词
                prompt = self.PromptModelHub.gen_required_argument_tool_selection_prompt(query, required_argument, tools)
                # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让 LLM 裁决唯一最匹配的工具
                model_output = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature, self.top_p)
                # 调用 prompt 包的 PromptModelHub.post_process_tool_selection_result()，从 LLM 输出解析出最终工具对象
                final_tool = self.PromptModelHub.post_process_tool_selection_result(model_output, tools)

            # 打日志：记录最终选中的工具
            logger.info(f"查询: [{query}]被选择工具 : [{final_tool.tool_id}] {final_tool.operationId}-{final_tool.name_for_human}")
        except Exception as e:
            # 底层实现，不用看：except ≈ catch(Exception e)，捕获所有异常兜底
            logger.error(f"检索并选择工具[{query}：{required_argument}]失败: {e}\n{traceback.format_exc()}")
            # 返回 None 表示选工具失败（≈ 返回 null）
            return None

        # 返回最终选中的工具对象
        return final_tool


# if __name__ == "__main__"：直接运行本文件时才执行的本地测试（≈ Java 的 main 方法）
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
    # 创建本类实例，准备做工具选择测试
    apiSelectionHub = ApiSelectionHub(milvus_uri, model_path, milvus_db_name, model, temperature, top_p,
                                      mongo_host, mongo_db, mongo_port, base_url,api_key)
    # 调用本类 get_tool_coarse_and_fine()，测试"查询苹果产品信息"能选出哪个工具
    tool = apiSelectionHub.get_tool_coarse_and_fine("查询苹果产品信息", None, topK)
