# models/__init__.py —— 【不用学】models 包出口，统一导出内部类（≈ 统一入口）

# 导出大语言模型调用封装类
from .llm import LargeLanguageModel
# 导出远程文本转向量封装类
from .remote_embedding_model import RemoteEmbeddingModel
