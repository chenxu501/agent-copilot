# prompt_hub.py —— 工厂函数：根据 .env 的 model_name 自动选 qwen 或 DeepSeek 那套提示词

# 导入包内公开的基类和千问子类，供下面工厂方法实例化（from prompt import ≈ 同包引用）
from prompt import QwenModelPromptHub, PromptModelHub
# 导入 DeepSeek-V3.2 提示词子类（定义在 dsv32_model_prompts.py）
from prompt.dsv32_model_prompts import DSv32ModelPromptHub
# 导入项目自封装日志工具，打印当前选中的模型（≈ slf4j）
from utils import logger


# 工厂方法：按模型名挑提示词子类并实例化返回（≈ Factory.create，工厂方法模式）
def create_prompt_hub(model_name: str):
    # 打日志：准备使用哪个模型
    logger.info(f"准备使用模型： {model_name}")
    # 模型名含 qwen（忽略大小写）就用千问那套提示词（lower ≈ toLowerCase，in ≈ String.contains）
    if "qwen" in model_name.lower():
        # 创建千问版提示词子类实例（≈ new QwenModelPromptHub(...)）
        return QwenModelPromptHub("",model_name)
    # 模型名含 deepseek-v3.2 就用 DeepSeek 那套提示词
    elif "deepseek-v3.2" in model_name.lower():
        # 创建 DeepSeek 版提示词子类实例
        return DSv32ModelPromptHub("", model_name)
    # 其他模型没有定制话术
    else:
        # 退回通用基类兜底（≈ new PromptModelHub(...)）
        return PromptModelHub("")
