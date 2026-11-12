# param_extraction/param_extraction_hub.py —— 参数提取核心：从用户话里抠出接口参数并校验缺失

# 导入 entity 包的 Tool 实体类（含 request_body 参数定义，≈ domain.Tool）
from entity import Tool
# 导入 models/llm.py 的 LargeLanguageModel，调用大模型的客户端封装
from models import LargeLanguageModel
# 导入 prompt 包的提示词模板中心和工厂方法，负责拼装/解析抽参数提示词（≈ 模板引擎 + 策略模式）
from prompt import PromptModelHub, QwenModelPromptHub, create_prompt_hub
# 导入 tools/tool_manager.py 的 ToolManager，查工具元数据（≈ DAO/Repository）
from tools import ToolManager
# 导入 utils 包的日志对象
from utils import logger

# 参数提取中心：LLM 抽参数 + 类型校验补齐（≈ @RequestBody 参数绑定 + Bean Validation）
class ParamExtractionHub:

    # 构造方法：初始化 LLM 客户端和提示词中心，保存模型采样参数（≈ 构造方法注入依赖）
    def __init__(self, model, temperature, top_p, api_url, api_key):
        # 创建 models/llm.py 的 LargeLanguageModel 并持有，抽参数时用它调 LLM
        self.LargeLanguageModel = LargeLanguageModel(api_url, api_key)
        # 按模型名创建提示词中心（工厂方法，≈ 工厂模式）
        self.PromptModelHub = create_prompt_hub(model)
        # 保存模型名，调 LLM 时使用
        self.model = model
        # 保存采样温度，控制生成随机性
        self.temperature = temperature
        # 保存核采样概率 top_p，控制生成多样性
        self.top_p = top_p


    # 方法：校验提取的参数是否符合工具定义，返回缺失/不合法的参数列表
    def validate_params(self, tool: Tool, extractionParam):
        # 初始化缺失参数收集列表（list ≈ ArrayList）
        missing_param = []
        # 遍历 API 定义 request_body 里的每个入参，逐个检查缺失和类型
        for target_param in tool.request_body:
            # 必填参数却没提到：记为缺失
            if target_param.name not in extractionParam and target_param.required:
                # 把缺失参数加入列表
                missing_param.append(target_param)
                # 打调试日志：记录缺失参数名
                logger.debug(f"已添加[{tool.tool_id} - {tool.operationId}] 缺失参数：{target_param.name}")
            else:
                # 提到了但是空字符串：也算缺失
                if isinstance(extractionParam[target_param.name], str) and len(extractionParam[target_param.name]) == 0:
                    # 把空值参数加入缺失列表
                    missing_param.append(target_param)
                    # 打调试日志：记录缺失参数名
                    logger.debug(f"已添加[{tool.tool_id} - {tool.operationId}] 缺失参数：{target_param.name}")
                else:
                    # 声明是整数型却不是 int，进入强转流程
                    if (target_param.type == "int64" or target_param.type == "int32") and not isinstance(
                            extractionParam[target_param.name], int):
                        # 用 try 尝试类型强转，失败走 except 分支（try/except ≈ try/catch）
                        try:
                            # 底层实现，不用看：把值强转成 int（≈ Integer.parseInt）
                            extractionParam[target_param.name] = int(extractionParam[target_param.name])
                        except:
                            # 底层实现，不用看：强转失败进入本分支（bare except ≈ catch 所有异常）
                            extractionParam[target_param.name] = ""
                            # 把转不动的参数加入缺失列表
                            missing_param.append(target_param)
                            # 打调试日志：记录缺失参数名
                            logger.debug(f"已添加[{tool.tool_id} - {tool.operationId}] 缺失参数：{target_param.name}")
                    # 声明是浮点型却不是 float，进入强转流程
                    if target_param.type == "double" and not isinstance(extractionParam[target_param.name], float):
                        # 用 try 尝试类型强转，失败走 except 分支
                        try:
                            # 底层实现，不用看：把值强转成 float（≈ Double.parseDouble）
                            extractionParam[target_param.name] = float(extractionParam[target_param.name])
                        except:
                            # 底层实现，不用看：强转失败进入本分支
                            extractionParam[target_param.name] = ""
                            # 把转不动的参数加入缺失列表
                            missing_param.append(target_param)
                            # 打调试日志：记录缺失参数名
                            logger.debug(f"已添加[{tool.tool_id} - {tool.operationId}] 缺失参数：{target_param.name}")
        # 返回缺失参数列表
        return missing_param


    # 方法：用 LLM 从用户话里提取工具参数，返回 (参数字典, 缺失参数列表)
    def extraction_params(self, query, tool: Tool,apis_chain= None):
        # 取出该 API 的参数定义列表（名称/类型/描述/是否必填）
        request_body = tool.request_body

        # 调用 prompt 包的 PromptModelHub.gen_get_all_parameters_prompt()，拼出"抽参数"提示词
        prompt = self.PromptModelHub.gen_get_all_parameters_prompt(query, request_body, apis_chain)
        # 调用 models/llm.py 的 LargeLanguageModel.chat_completions()，让大模型从用户话里抠接口参数
        model_output = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature, self.top_p)
        # 打调试日志：记录 LLM 的原始输出
        logger.debug(f"提取工具参数模型输出：{model_output}")
        # 调用 prompt 包的 PromptModelHub.post_process_get_all_parameter_result()，把 LLM 输出解析成参数字典
        results = self.PromptModelHub.post_process_get_all_parameter_result(model_output, tool)
        # 调用本类 validate_params()，校验类型并找出缺失/不合法参数
        missing_param = self.validate_params(tool, results)
        # 返回参数字典和缺失参数列表
        return results, missing_param
