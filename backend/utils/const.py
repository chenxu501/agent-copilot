# const.py —— 常量定义：HTTP 状态码常量、新用户默认权限列表

# 任务处理失败状态码（404 Not Found）
TASK_ERROR_CODE = 404
# 任务处理成功状态码（200 OK）
TASK_SUCCESS_CODE = 200
# 接口响应：成功（200 OK）
RESPONSE_STATUS_CODE_SUCCESS = 200
# 接口响应：失败/资源不存在（404）
RESPONSE_STATUS_CODE_ERROR = 404
# 接口响应：未认证（没登录/令牌无效/令牌过期，401 Unauthorized）
RESPONSE_AUTH_CODE_ERROR = 401
# 接口响应：已登录但无权限访问该接口（403 Forbidden）
RESPONSE_ALLOW_CODE_ERROR = 403
# 新注册用户的默认权限：只能登录/登出/执行任务/查任务，不能管理工具（权限名 = app.py 接口函数名，require_permission 按它校验）
DEFAULT_PERMISSIONS = ['login', 'logout', 'mesh_query', 'get_task_status']
