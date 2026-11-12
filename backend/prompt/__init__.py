# __init__.py —— prompt 包的导出入口：把常用类抬到包顶层，外部可直接 from prompt import xxx

# 导出基类：通用提示词模板 + 解析工具，外部写 from prompt import PromptModelHub 即可用（≈ 导出抽象基类）
from .general_prompts import PromptModelHub
# 导出千问提示词子类（≈ 导出 qwen 策略实现）
from .qwen_model_prompts import QwenModelPromptHub
# 导出工厂方法：按模型名创建对应提示词子类（≈ 导出 Factory.create）
from .prompt_hub import create_prompt_hub
