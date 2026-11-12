# use_manager/__init__.py —— use_manager 包统一出口：导出用户管理类

# 从 user_manager.py 导出用户管理类（注册/登录/登出），≈ UserService
from .user_manager import UserManagerHub
