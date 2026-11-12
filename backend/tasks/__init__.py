# tasks/__init__.py —— tasks 包出口：导出任务管理器和任务生成中心两个核心类

# 从本包 task_manager.py 导入 TaskManager，任务在 MongoDB 里的增查改（≈ Repository）
from .task_manager import TaskManager
# 从本包 generate_task_hub.py 导入 GenerateTaskHub，LLM 拆任务/补参查询/安全校验
from .generate_task_hub import GenerateTaskHub
