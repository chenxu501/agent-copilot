# tool_summary_hub.py —— 工具结果总结中心：让大模型把接口返回压缩成人话总结

# 从 entity/tool_entity.py 导入 Tool 实体（此处仅作类型参考）
from entity import Tool
# 从 models/llm.py 导入大语言模型调用封装（≈ 调大模型接口的 Client）
from models import LargeLanguageModel
# 从 prompt 包导入提示词模板中心和工厂方法 create_prompt_hub
from prompt import PromptModelHub, QwenModelPromptHub, create_prompt_hub

# 从 utils/__init__.py 取全局日志器
from utils import logger


# 工具结果总结类：整条 API 调用链跑完后生成给用户看的最终答复
class ToolSummaryHub:
    """
    ToolSummaryHub 类的初始化方法。

    参数:
        model (str): 使用的大语言模型名称。
        temperature (float): 控制生成文本随机性的温度参数，取值范围通常在 0 到 1 之间。
        top_p (float): 核采样的概率阈值，取值范围通常在 0 到 1 之间。

    属性:
        LargeLanguageModel (LargeLanguageModel): 大语言模型实例。
        PromptModelHub (PromptModelHub): 提示词模型中心实例。
        model (str): 使用的大语言模型名称。
        temperature (float): 控制生成文本随机性的温度参数。
        top_p (float): 核采样的概率阈值。
    """

    # 构造方法：初始化 LLM 客户端、提示词中心，保存模型采样参数
    def __init__(self, model, temperature, top_p, api_url, api_key):
        """构造方法（≈ Java 构造方法）：初始化 LLM 客户端、提示词中心，并保存模型采样参数。"""
        # 调用 models/llm.py 创建大语言模型客户端（≈ new RestTemplate）
        self.LargeLanguageModel = LargeLanguageModel(api_url, api_key)
        # 调用 prompt 包的工厂方法 create_prompt_hub() 按模型名创建提示词中心
        self.PromptModelHub = create_prompt_hub(model)
        # 保存大模型名称
        self.model = model
        # 保存温度参数（越低回答越稳定）
        self.temperature = temperature
        # 保存核采样阈值 top_p
        self.top_p = top_p

    # 按固定长度把字符串切成多段
    def split_string_by_length(self, s, length):
        """
        将字符串 s 按照指定的长度 length 分割成多个子字符串，并返回一个列表。
        :param s: 要分割的字符串
        :param length: 每个子字符串的最大长度
        :return: 包含子字符串的列表
        """
        # 列表推导式按步长 length 切片返回（≈ Guava Splitter.fixedLength）
        return [s[i:i + length] for i in range(0, len(s), length)]

    # 对超长的 API 调用结果做分块压缩总结，防止撑爆大模型输入长度
    def summary_large_result(self, query, apis):
        """
        对"结果超长"的 API 调用记录做分块总结压缩。
        :param query: 用户查询（当前实现未直接使用）
        :param apis: list[dict] —— API 调用结果链，每个元素含 tool/task_description/result 等
        :return: list —— 处理后的 API 调用结果链（超长 result 已被分块总结替换）
        """
        # 标记位：先假设所有结果都不超长
        flag = True
        # 遍历每个调用结果检查长度
        for tmp in apis:
            # 判断单个结果是否不超过 10 万字符
            if len(tmp["result"]) <= 100000:
                # 不超长就 continue 检查下一个
                continue
            # 超长走 else
            else:
                # 置标记位为 False，表示需要分块总结
                flag = False
        # 判断是否全部都不超长
        if flag:
            # 全都不超长：原样返回
            return apis
        # 存在超长结果走 else
        else:
            # 遍历每个调用结果
            for tmp in apis:
                # 只处理超长的结果
                if len(tmp["result"]) > 100000:
                    # 收集各分块总结后拼接（+= ≈ StringBuilder append）
                    node_results = ""
                    # 取工具描述
                    api_description = tmp["tool"]
                    # 取任务描述
                    task_description = tmp["task_description"]
                    # 调本类 split_string_by_length() 把结果切成 10 万字符一段
                    split_str_list = self.split_string_by_length(tmp["result"], 100000)
                    # 遍历每一段，逐段让大模型压缩总结
                    for chunk in split_str_list:
                        # 调 prompt 包的 chunk_tool_summary_prompt() 拼"分块总结"提示词
                        prompt = self.PromptModelHub.chunk_tool_summary_prompt(task_description=task_description,
                                                                               api_description=api_description,
                                                                               chunk_result=chunk)
                        # 调用 models/llm.py 的 chat_completions() 让大模型总结这一段
                        model_output = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature,
                                                                                self.top_p)
                        # 打印模型输出日志
                        logger.info(model_output)
                        # 拼接各段总结
                        node_results += model_output
                    # 用压缩后的总结替换原始超长结果
                    tmp["result"] = node_results
            # 返回处理后的结果链
            return apis

    # 对整条调用链生成最终的人话总结
    def tool_summary(self, query, apis):
        """
        生成工具摘要的函数。
            功能:
                根据输入的查询内容和 API 列表，生成对应的工具摘要。通过提示词模型生成提示词，
                再使用大语言模型生成最终的摘要内容。
            参数:
                query (str): 用户的查询内容。
                apis (list): API 列表，用于生成工具摘要。
            返回值:
                str: 大语言模型生成的工具摘要内容。
            代码流程逻辑:
                1. 调用 PromptModelHub 实例的 gen_tool_summary_prompt 方法，根据查询内容和 API 列表生成提示词。
                2. 调用 LargeLanguageModel 实例的 chat_completions 方法，传入生成的提示词、模型名称、温度参数和核采样阈值，获取模型输出。
                3. 打印模型输出。
                4. 返回模型输出。
            """
        # 先调本类 summary_large_result() 压缩超长结果，防止提示词过长
        apis = self.summary_large_result(query, apis)
        # 调 prompt 包的 gen_tool_summary_prompt() 拼"总结整条调用链"的提示词
        prompt = self.PromptModelHub.gen_tool_summary_prompt(query, apis)
        # 调用 models/llm.py 的 chat_completions() 生成最终总结
        model_output = self.LargeLanguageModel.chat_completions(prompt, self.model, self.temperature, self.top_p)
        # 打印模型输出日志
        logger.info(model_output)
        # 返回总结文本给上层（最终答给用户）
        return model_output

