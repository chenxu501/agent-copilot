# app.py —— 后端总入口：定义 10 个 HTTP 接口、JWT 鉴权、启动 Flask 服务

# 导入 json 模块，做 JSON 序列化/反序列化（≈ Jackson / Gson）
import json
# 导入 time 模块，用 time.sleep 等待上传文件落盘（≈ Thread.sleep）
import time
# 导入 flask_cors 的 CORS，放行前端跨域请求（≈ Spring 的 CORS 过滤器）
from flask_cors import CORS
# 从 flask 导入核心对象：Web 应用、JSON 响应、请求对象、请求级变量 g（≈ ThreadLocal）
from flask import Flask, jsonify, request, g
# 导入 flasgger 的 Swagger，按函数 docstring 自动生成接口文档 /apidoc（≈ SpringDoc）
from flasgger import Swagger
# 导入 ApiPlanningHub（apis/api_planning_hub.py）：AI 任务编排核心类（拆任务→选工具→提参数→调接口→总结）
from apis.api_planning_hub import ApiPlanningHub
# 导入实体类 Parameter、Tool（entity 模块），封装工具及其参数（≈ @Document 实体）
from entity import Parameter, Tool
# 导入 GenerateTaskHub（tasks 模块），把多轮对话上下文拼成请求文本
from tasks import GenerateTaskHub
# 导入 LargeLanguageModel（models 模块），大模型调用封装（≈ 第三方 AI SDK 客户端）
from models import LargeLanguageModel
# 导入 ToolManager（tools/tool_manager.py）：工具增删查、上传解析入库（≈ ToolService）
from tools.tool_manager import ToolManager
# 导入 TaskManager（tasks 模块）：创建任务、更新进度、查询任务（≈ TaskService）
from tasks import TaskManager
# 导入 UserManagerHub（use_manager/user_manager.py）：注册/登录/登出（≈ UserService）
from use_manager.user_manager import UserManagerHub
# 从 utils 导入统一状态码常量和新用户默认权限（≈ 常量类）
from utils import RESPONSE_AUTH_CODE_ERROR, RESPONSE_ALLOW_CODE_ERROR, RESPONSE_STATUS_CODE_SUCCESS, DEFAULT_PERMISSIONS
# 从 utils/logger_config.py 导入日志器（≈ SLF4J 的 Logger）
from utils.logger_config import setup_logger,logger
# 导入 traceback，异常时拼接堆栈文本（底层实现，不用看：≈ e.printStackTrace()）
import traceback
# 导入 os，获取 CPU 核心数、拼接文件路径（≈ System.getProperty / File）
import os
# 导入线程池 ThreadPoolExecutor，异步执行耗时的 AI 任务（≈ ExecutorService）
from concurrent.futures import ThreadPoolExecutor
# 调用 utils/config.py 读取 .env 中的 mongo_host 等数据库与模型配置（≈ @ConfigurationProperties）
from utils.config import (
    milvus_uri,
    model_path,
    milvus_db_name,
    model_name,
    model_temperature,
    model_top_p,
    mongo_host,
    mongo_db,
    mongo_port,
    topK,
    model_api_key,
    model_base_url, SECRET_KEY, JWT_ALGORITHM,
)
# 导入 PyJWT，生成/校验 JWT 登录令牌（≈ jjwt / java-jwt）
import jwt
# 导入 datetime、timedelta，计算令牌过期时间（≈ LocalDateTime + Duration）
from datetime import datetime, timedelta
# 导入 uuid，给令牌生成全局唯一 ID（≈ java.util.UUID）
import uuid
# 导入 TTLCache，存用户会话的本地缓存（≈ Caffeine 的 expireAfterWrite 缓存）
from cachetools import TTLCache
# 导入 wraps，装饰器保留原函数信息（底层实现，不用看：@wraps 元数据处理）
from functools import wraps

# 设置 JWT 登录令牌有效期为 1 小时（≈ jjwt 的 setExpiration）
JWT_EXPIRATION_DELTA = timedelta(hours=1)

# 创建 TTL 会话缓存：key=令牌、value=用户信息，最多 1000 条、1 小时自动过期（≈ Caffeine）
session_cache = TTLCache(maxsize=1000, ttl=3600)

# 创建 Flask 应用实例（≈ SpringApplication.run，内嵌 Web 容器）
app = Flask(__name__)

# 调用 os.cpu_count() 获取 CPU 核心数（≈ Runtime.getRuntime().availableProcessors()）
cpu_count = os.cpu_count()
# 拿不到 CPU 核心数时走兜底分支
if cpu_count is None:
    # 兜底线程数取 8
    max_workers = 8
# 能拿到核心数时走这个分支
else:
    # IO 密集型经验值：线程数 = CPU 核心数 × 2
    max_workers = cpu_count * 2
# 创建全局线程池，用来异步跑耗时的 AI 任务（≈ ExecutorService）
executor = ThreadPoolExecutor(max_workers)
# 预留的任务状态字典（dict ≈ HashMap），实际状态存 MongoDB 的 task 表
tasks = {}

# 配置跨域白名单：只放行前端 http://localhost:3000 访问下列接口（≈ Spring 的 CORS 配置）
CORS(app, resources={r"/login_user": {"origins": "http://localhost:3000"},
                        r"/register_user": {"origins": "http://localhost:3000"},
                        r"/get_all_tools": {"origins": "http://localhost:3000"},
                        r"/delete_all_tool": {"origins": "http://localhost:3000"},
                        r"/upload_tool": {"origins": "http://localhost:3000"},
                        r"/delete_tool_by_ids": {"origins": "http://localhost:3000"},
                        r"/test_llm": {"origins": "http://localhost:3000"},
                        r"/api_task_status": {"origins": "http://localhost:3000"},
                        r"/api_planning": {"origins": "http://localhost:3000"}})
# 开启接口文档自动生成，浏览器访问 http://localhost:5001/apidoc（≈ SpringDoc/Swagger UI）
Swagger(app)

# 创建工具管理器 ToolManager：连 MongoDB + Milvus，负责工具增删查与上传解析（≈ @Service ToolService）
toolManager = ToolManager(mongo_host, mongo_db, mongo_port, milvus_uri, milvus_db_name)
# 创建任务管理器 TaskManager：连 MongoDB task 表，负责创建/更新/查询任务（≈ TaskService）
taskManager = TaskManager(mongo_host, mongo_db, mongo_port)

# 创建用户管理器 UserManagerHub：负责注册/登录/登出（≈ UserService）
userManagerHub = UserManagerHub(mongo_host, mongo_db, mongo_port)

# 定义鉴权装饰器 require_permission（≈ 自定义注解 + HandlerInterceptor 拦截器）
def require_permission(f):
    # 底层实现，不用看：@wraps 保留原接口函数的名称、文档等元信息
    @wraps(f)
    # 定义包装函数：先鉴权、后放行原接口函数
    def decorated_function(*args, **kwargs):
        # 判断是否免鉴权接口：register、login 是公开接口
        if f.__name__ in ['register', 'login']:
            # 免鉴权直接执行原接口函数（≈ 放行）
            return f(*args, **kwargs)

        # 从请求头取 Authorization 字段（≈ request.getHeader("Authorization")）
        auth_header = request.headers.get('Authorization')
        # 没有 Authorization 头就返回 401
        if not auth_header:
            # 调用 flask 的 jsonify 生成 JSON 响应：未提供认证令牌
            return jsonify({
                "status": RESPONSE_AUTH_CODE_ERROR,
                "message": "未提供认证令牌",
                "data": None
            }), RESPONSE_AUTH_CODE_ERROR

        # 用 try 执行令牌校验，出异常统一按认证失败返回
        try:
            # 校验令牌格式必须以 "Bearer " 开头
            if not auth_header.startswith('Bearer '):
                # 格式不对：返回 401 无效的令牌格式
                return jsonify({
                    "status": RESPONSE_AUTH_CODE_ERROR,
                    "message": "无效的令牌格式",
                    "data": None
                }), RESPONSE_AUTH_CODE_ERROR

            # 按空格切分取出真正的令牌字符串（"Bearer xxx" 的第二段）
            token = auth_header.split(' ')[1]

            # 查会话缓存 session_cache，看这个令牌是否已登录
            if token not in session_cache:
                # 缓存里没有：返回 401 令牌无效或已过期
                return jsonify({
                    "status": RESPONSE_AUTH_CODE_ERROR,
                    "message": "令牌无效或已过期",
                    "data": None
                }), RESPONSE_AUTH_CODE_ERROR

            # 调用 pyjwt 的 jwt.decode 解码令牌，同时校验签名和有效期
            try:
                # 解码得到载荷 payload（含 user_id / username / user_authority）
                payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
            # 捕获令牌过期异常（≈ catch ExpiredSignatureError）
            except jwt.ExpiredSignatureError:
                # 过期令牌先从会话缓存里清掉
                if token in session_cache:
                    # 删除缓存中这条会话记录
                    del session_cache[token]
                # 返回 401 令牌已过期
                return jsonify({
                    "status": RESPONSE_AUTH_CODE_ERROR,
                    "message": "令牌已过期",
                    "data": None
                }), RESPONSE_AUTH_CODE_ERROR
            # 捕获签名错误等无效令牌异常（≈ catch InvalidTokenError）
            except jwt.InvalidTokenError:
                # 返回 401 无效的令牌
                return jsonify({
                    "status": RESPONSE_AUTH_CODE_ERROR,
                    "message": "无效的令牌",
                    "data": None
                }), RESPONSE_AUTH_CODE_ERROR

            # 把缓存里的用户信息放进 flask 的 g 对象（请求级变量 ≈ ThreadLocal），供后面使用
            g.current_user = session_cache[token]

            # 校验用户权限列表里是否包含当前接口函数名（权限名 = 函数名）
            if f.__name__ not in g.current_user['user_authority']:
                # 没权限：返回 403 禁止访问
                return jsonify({
                    "status": RESPONSE_ALLOW_CODE_ERROR,
                    "message": f"没有权限访问 {f.__name__} 接口",
                    "data": None
                }), RESPONSE_ALLOW_CODE_ERROR

        # 捕获认证过程中的所有异常（≈ catch Exception）
        except Exception as e:
            # 底层实现，不用看：logger.error 写一条认证失败日志
            logger.error(f"认证失败: {str(e)}")
            # 返回 401 认证失败响应
            return jsonify({
                "status": RESPONSE_AUTH_CODE_ERROR,
                "message": "认证失败",
                "data": None
            }), RESPONSE_AUTH_CODE_ERROR

        # 鉴权全部通过，执行真正的接口函数（≈ 拦截器放行）
        return f(*args, **kwargs)
    # 返回包装后的函数，用它替换原接口函数（装饰器生效）
    return decorated_function


# 定义路由 /delete_all_tool（≈ @GetMapping）：清空所有工具
@app.route('/delete_all_tool', methods=['GET'])
# 挂鉴权装饰器 require_permission：校验 JWT 令牌和 delete_tool_db 权限
@require_permission
# 接口函数（权限名 = 函数名 delete_tool_db）：清空工具库
def delete_tool_db():
    # 下面 docstring 是 Swagger 接口文档（flasgger 渲染到 /apidoc），不用看
    """
            工具数据库删除
            ---
            tags:
              - Tool Delete
            description:
                上传文件到服务器
            responses:
              200:
                description: 数据库清空成功
              400:
                description: 数据库未清空成功
        """

    # 调用 tools/tool_manager.py 的 ToolManager.delete_all_tools()，清空 MongoDB 和 Milvus 里的全部工具
    toolManager.delete_all_tools()
    # 返回成功响应 {"message": "delete tool success!"}（≈ Result.ok）
    return jsonify({'message': 'delete tool success! '}), RESPONSE_STATUS_CODE_SUCCESS


# 定义路由 /insert_tool（≈ @PostMapping）：新增单个工具
@app.route('/insert_tool', methods=['POST'])
# 挂鉴权装饰器：校验 JWT 令牌和 insert_tool 权限
@require_permission
# 接口函数（权限名 = 函数名 insert_tool）：把一个工具及其参数插入数据库
def insert_tool():
    # 下面 docstring 是 Swagger 接口文档（含请求体字段说明），不用看
    """
    工具插入
    ---
    tags:
      - Tool Management
    description:
        插入一个新的工具到数据库中
    parameters:
      - name: body
        in: body
        required: true
        schema:
          id: Tool Insert Request
          required:
            - operationId
            - name_for_human
            - name_for_model
            - description
            - url
            - path
            - method
            - params
          properties:
            operationId:
              type: string
              description: 操作ID
            name_for_human:
              type: string
              description: 人类可读的工具名称
            name_for_model:
              type: string
              description: 模型使用的工具名称
            description:
              type: string
              description: 工具的描述
            url:
              type: string
              description: API 的 URL
            path:
              type: string
              description: API 的路径
            method:
              type: string
              description: HTTP 方法 (如 GET, POST 等)
            params:
              type: array
              items:
                type: object
                properties:
                  param_name:
                    type: string
                    description: 参数名称
                  paramType:
                    type: string
                    description: 参数类型
                  param_description:
                    type: string
                    description: 参数描述
                  enum:
                    type: array
                    items:
                      type: string
                    description: 参数的枚举值
                  in_:
                    type: string
                    description: 参数的位置 (如 query, body 等)
    responses:
      200:
        description: 工具插入成功
        schema:
          type: object
          properties:
            message:
              type: string
      400:
        description: 请求参数缺失或无效
        schema:
          type: object
          properties:
            error:
              type: string
    """

    # 调用 request.get_json() 解析请求体 JSON（≈ @RequestBody）
    data = request.get_json()
    # 请求体为空：返回 400
    if not data:
        # 返回错误响应：缺少查询参数
        return jsonify({'error': 'Missing query parameter'}), 400

    # 创建空列表装参数实体（list ≈ ArrayList）
    params = []
    # 遍历请求体里的每个参数定义
    for tmp in data["params"]:
        # 调用 entity.Parameter 构造一个参数实体（名称/类型/描述/枚举/位置）
        parameter = Parameter(
            name=tmp["param_name"],
            type=tmp["paramType"],
            description=tmp["param_description"],
            enum=tmp["enum"],
            required=True,
            in_=tmp["in_"]
        )
        # 把参数实体追加进列表（≈ list.add）
        params.append(parameter)

    # 调用 entity.Tool 构造工具实体，封装工具基本信息和参数列表
    tool = Tool(
        tool_id=0,
        operationId=data["operationId"],
        name_for_human=data["name_for_human"],
        name_for_model=data["name_for_model"],
        description=data["description"],
        api_url=data["url"],
        path=data["path"],
        method=data["method"],
        request_body=params
    )
    # 调用 ToolManager.insert_tools([tool]) 把工具写入 MongoDB 和 Milvus
    toolManager.insert_tools([tool])
    # 返回成功响应（≈ Result.ok）
    return jsonify({'message': 'delete tool success! '}), RESPONSE_STATUS_CODE_SUCCESS


# 定义路由 /register_user（≈ @PostMapping）：用户注册，公开接口无需令牌
@app.route('/register_user', methods=['POST'])
# 接口函数 register：校验参数后创建新用户
def register():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
    用户注册
    ---
    tags:
      - User Management
    description:
        注册新用户
    parameters:
      - name: body
        in: body
        required: true
        schema:
          id: User Registration Request
          required:
            - userName
            - password
            - confirm_password
          properties:
            userName:
              type: string
              description: 用户名
            password:
              type: string
              description: 密码
            confirm_password:
              type: string
              description: 确认密码
    responses:
      200:
        description: 用户注册成功
        schema:
          type: object
          properties:
            message:
              type: string
              example: "create user success!"
      400:
        description: 用户注册失败
        schema:
          type: object
          properties:
            message:
              type: string
              example: "create user failed!"
      409:
        description: 用户名已存在
        schema:
          type: object
          properties:
            message:
              type: string
              example: "该用户已注册"
    """
    # 调用 request.get_json() 解析请求体 JSON（≈ @RequestBody）
    data = request.get_json()
    # 请求体为空：返回 400
    if not data:
        # 返回错误响应：缺少查询参数
        return jsonify({'error': 'Missing query parameter'}), 400

    # 列出注册必填字段：用户名、密码、确认密码
    required_fields = ["username", "password", "confirm"]
    # 用 all(...) 校验三个字段是否都在请求体里
    if not all(field in data for field in required_fields):
        # 缺字段：返回 400 并提示补齐
        return jsonify({'message': '缺少必要的字段: username, password, confirm'}), 400

    # 从请求体取出用户名
    userName = data["username"]
    # 从请求体取出密码
    password = data["password"]
    # 从请求体取出确认密码
    confirm_password = data["confirm"]
    # 调用 UserManagerHub.create_user() 创建用户（底层实现，不用看：密码 bcrypt 加密入库），返回状态码和消息
    status_code, message = userManagerHub.create_user(userName, password, confirm_password, DEFAULT_PERMISSIONS)
    # 状态码 200 表示创建成功
    if status_code == RESPONSE_STATUS_CODE_SUCCESS:
        # 底层实现，不用看：logger.info 记一条创建成功日志
        logger.info(f"成功创建用户")
        # 返回注册成功响应
        return jsonify({'message': 'create user success!'}), RESPONSE_STATUS_CODE_SUCCESS
    # 状态码 409 表示用户名已存在
    elif status_code == 409:
        # 底层实现，不用看：logger.warning 记录重复注册告警
        logger.warning(f"尝试注册已存在的用户: {userName}")
        # 返回 409：该用户已注册
        return jsonify({'message': '该用户已注册'}), 409
    # 其他状态码：创建失败
    else:
        # 底层实现，不用看：logger.error 记录失败原因
        logger.error(f"创建用户失败: {userName}, 原因: {message}")
        # 把 UserManagerHub 返回的错误消息和状态码原样返回给前端
        return jsonify({'message': message}), status_code


# 定义路由 /login_user（≈ @PostMapping）：用户登录，公开接口无需令牌
@app.route('/login_user', methods=['POST'])
# 接口函数 login：校验账号密码并签发 JWT 令牌
def login():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
    用户登录
    ---
    tags:
      - User Management
    description:
        用户登录接口
    parameters:
      - name: body
        in: body
        required: true
        schema:
          id: User Login Request
          required:
            - userName
            - password
          properties:
            userName:
              type: string
              description: 用户名
            password:
              type: string
              description: 密码
    responses:
      200:
        description: 用户登录成功
        schema:
          type: object
          properties:
            status:
              type: integer
              example: 200
            message:
              type: string
              example: "登录成功"
            data:
              type: object
              properties:
                token:
                  type: object
                  properties:
                    access_token:
                      type: string
                      example: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
                    expires_in:
                      type: integer
                      example: 3600
                    token_type:
                      type: string
                      example: "Bearer"
      400:
        description: 用户登录失败
        schema:
          type: object
          properties:
            message:
              type: string
              example: "登录失败！请检查用户名和密码"
    """
    # 调用 request.get_json() 解析请求体 JSON（≈ @RequestBody）
    data = request.get_json()
    # 请求体为空：返回 400
    if not data:
        # 返回错误响应：缺少查询参数
        return jsonify({'error': 'Missing query parameter'}), 400

    # 从请求体取出用户名
    userName = data["username"]
    # 从请求体取出密码
    password = data["password"]
    # 调用 UserManagerHub.login() 校验用户名密码，返回用户对象
    user = userManagerHub.login(userName, password)
    # user_id > 0 表示登录成功
    if user.user_id > 0:
        # 底层实现，不用看：logger.info 记录登录成功
        logger.info(f"登录成功")

        # 生成 JWT 登录令牌（调用 pyjwt 的 jwt.encode），载荷含用户 id/姓名/权限，有效期 1 小时
        access_token = jwt.encode({
            'jti': str(uuid.uuid4()),
            'user_id': user.user_id,
            'username': user.userName,
            'user_authority': user.user_authority,
            'exp': datetime.utcnow() + JWT_EXPIRATION_DELTA
        }, SECRET_KEY, algorithm=JWT_ALGORITHM)

        # 底层实现，不用看：logger.debug 打印刚生成的令牌
        logger.debug(f"生成访问令牌: {access_token}")

        # 把用户信息写进会话缓存 session_cache，key 为令牌（后续鉴权靠它查）
        session_cache[access_token] = {
            'user_id': user.user_id,
            'username': user.userName,
            'user_authority': user.user_authority
        }

        # 底层实现，不用看：logger.debug 记录令牌已入缓存
        logger.debug(f"用户访问令牌: {access_token}已存入本地缓存")

        # 返回登录成功响应，把 access_token 等信息交给前端（≈ Result<Token>）
        return jsonify({
            "status": RESPONSE_STATUS_CODE_SUCCESS,
            "message": "登录成功",
            "auth_data": {
                "token": {
                    "access_token": access_token,
                    "expires_in": 3600,
                    "token_type": "Bearer"
                }
            }
        }), 200
    # user_id <= 0 表示用户名或密码错误
    else:
        # 返回 400：登录失败
        return jsonify({'message': '登录失败！请检查用户名和密码'}), 400


# 定义路由 /logout_user（≈ @PostMapping）：用户登出
@app.route('/logout_user', methods=['POST'])
# 接口函数 logout：手动校验请求头令牌后删除会话
def logout():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
    登出用户
    ---
    tags:
      - user management
    description:
      用户登出接口，通过 POST 方法接收用户 ID 并执行登出操作。
    parameters:
      - name: body
        in: body
        required: true
        schema:
          id: logout_body
          required:
            - user_id
          properties:
            user_id:
              type: integer
              format: int32
              description: 需要登出的用户 ID。
    responses:
      200:
        description: 登出成功
        schema:
          type: object
          properties:
            message:
              type: string
              example: logout success!
      400:
        description: 登出失败或缺少参数
        schema:
          type: object
          properties:
            error:
              type: string
              example: logout failed! 或 Missing query parameter
    """
    # 从 Authorization 请求头取令牌
    auth_header = request.headers.get('Authorization')
    # 请求头缺失或不是 Bearer 格式：返回 400
    if not auth_header or not auth_header.startswith('Bearer '):
        # 返回错误响应：令牌格式错误
        return jsonify({'error': 'Invalid token format'}), 400

    # 按空格切分取出真正的令牌字符串
    token = auth_header.split(' ')[1]

    # 判断令牌是否还在会话缓存里
    if token in session_cache:
        # 从会话缓存删除该令牌（= 注销登录状态）
        del session_cache[token]

    # 返回登出成功响应
    return jsonify({'message': 'logout success!'}), RESPONSE_STATUS_CODE_SUCCESS


# 定义路由 /delete_tool_by_ids（≈ @PostMapping）：按 ID 批量删除工具
@app.route('/delete_tool_by_ids', methods=['POST'])
# 挂鉴权装饰器：校验 JWT 令牌和 delete_tool_db_by_ids 权限
@require_permission
# 接口函数（权限名 = 函数名 delete_tool_db_by_ids）：按 id 列表删工具
def delete_tool_db_by_ids():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
特定id工具数据库删除
---
tags:
  - Tool Delete By Ids
description:
    根据提供的ID列表删除工具
parameters:
  - name: body
    in: body
    required: true
    schema:
      id: Tool Delete Request
      required:
        - ids
      properties:
        ids:
          type: array
          items:
            type: integer
          description: 需要删除的工具ID列表
responses:
  200:
    description: 数据库删除成功
    schema:
      type: object
      properties:
        message:
          type: string
  400:
    description: 数据库未删除成功
    schema:
      type: object
      properties:
        error:
          type: string
"""
    # 调用 request.get_json() 解析请求体 JSON（≈ @RequestBody）
    data = request.get_json()
    # 请求体为空或没有 ids 字段：返回 400
    if not data or 'ids' not in data:
        # 返回错误响应：缺少查询参数
        return jsonify({'error': 'Missing query parameter'}), 400

    # 从请求体取出要删除的工具 id 列表
    ids = data['ids']
    # 调用 ToolManager.delete_tools(ids) 按 id 批量删除工具
    toolManager.delete_tools(ids)
    # 底层实现，不用看：logger.info 记录删除成功日志
    logger.info(f"工具删除成功")
    # 返回成功响应（≈ Result.ok）
    return jsonify({'message': 'delete tool success! '}), RESPONSE_STATUS_CODE_SUCCESS


# 定义路由 /upload_tool（≈ @PostMapping + MultipartFile）：上传工具文件批量导入
@app.route('/upload_tool', methods=['POST'])
# 挂鉴权装饰器：校验 JWT 令牌和 upload_file 权限
@require_permission
# 接口函数（权限名 = 函数名 upload_file）：保存并解析工具文件
def upload_file():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
        文件上传接口
        ---
        tags:
          - File Upload
        description:
            上传文件到服务器
        parameters:
          - name: file
            in: formData
            type: file
            required: true
            description: 要上传的文件
        responses:
          200:
            description: 文件上传成功，重定向到主页
          400:
            description: 未上传文件或文件名为空
    """
    # 检查 multipart 表单里有没有名为 file 的文件字段
    if 'file' not in request.files:
        # 没有文件：返回 400
        return jsonify({'error': '没有文件部分'}), 400

    # 取出上传的文件对象（≈ MultipartFile）
    uploaded_file = request.files['file']
    # 文件名非空才继续处理
    if uploaded_file.filename != '':
        # 把文件保存到服务端 ./api_data/ 目录
        uploaded_file.save('./api_data/' + uploaded_file.filename)

        # 等待 5 秒让文件写盘完成（time.sleep(5) ≈ Thread.sleep）
        time.sleep(5)

        # 调用 ToolManager.upload_file() 解析文件：工具数据写 MongoDB、向量写 Milvus（供 AI 语义检索选工具）
        toolManager.upload_file('./api_data/' + uploaded_file.filename)
        # 底层实现，不用看：logger.info 记录上传成功日志
        logger.info(f"文件上传成功")
        # 返回上传成功响应
        return jsonify({'message': 'upload file success! '}), RESPONSE_STATUS_CODE_SUCCESS
    # 文件名为空的分支
    else:
        # 返回 400：没有上传文件或文件名为空
        return jsonify({'error': 'No file uploaded or filename is empty'}), 400


# 定义路由 /get_all_tools（≈ @GetMapping）：查询所有工具
@app.route('/get_all_tools', methods=['GET'])
# 挂鉴权装饰器：校验 JWT 令牌和 get_all_tools 权限
@require_permission
# 接口函数（权限名 = 函数名 get_all_tools）：返回全部工具列表
def get_all_tools():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
            获取所有工具接口
            ---
            tags:
              - Tools
            description:
                获取服务器上所有工具的列表
            responses:
              200:
                description: 成功获取工具列表
              500:
                description: 服务器内部错误
        """
    # 调用 tools/tool_manager.py 的 ToolManager.get_all_tools()，从 MongoDB 查出全部工具
    datas = toolManager.get_all_tools()
    # 底层实现，不用看：logger.debug 打印查询结果
    logger.debug(f"Output: {datas}")
    # 返回工具列表 JSON（≈ Result<List<Tool>>）
    return jsonify({"results": datas}), RESPONSE_STATUS_CODE_SUCCESS


# 定义路由 /api_planning（≈ @PostMapping）：执行 AI 任务，项目最核心的接口
@app.route('/api_planning', methods=['POST'])
# 挂鉴权装饰器：校验 JWT 令牌和 mesh_query 权限
@require_permission
# 接口函数（权限名 = 函数名 mesh_query）：创建任务并把 AI 处理丢进线程池
def mesh_query():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
        Agent Planning
        ---
        tags:
            - Planning API
        description:
            Agent Planning接口，json格式
        parameters:
            - name: body
            in: body
            required: true
            schema:
                id: Planning Request body
                required:
                - query
            properties:
                modelName:
                    type: string
                    description: 模型名称
                    required: true
                temperature:
                    type: number
                    description: 温度参数
                    required: true
                api_key:
                    type: string
                    description: API 密钥
                    required: true
                api_url:
                    type: string
                    description: API 地址
                    required: true
                query:
                    type: string
                    description: 用户需求.
        responses:
            200:
                description: 转化成功
        """
    # 调用 request.get_json() 解析请求体 JSON（≈ @RequestBody）
    data = request.get_json()

    # 请求体为空：返回 400
    if not data:
        # 返回错误响应：缺少查询参数
        return jsonify({'error': 'Missing query parameter'}), 400
    # 有请求体的正常分支
    else:
        # 调用 TaskManager.create_task() 在 MongoDB 创建任务，生成 task_id
        task_id = taskManager.create_task()
        # 把耗时的 AI 处理提交到线程池异步执行（≈ @Async），先返回 task_id
        executor.submit(_process_task, task_id, data)
        # 立刻返回任务编号，前端拿它轮询 /api_task_status 看进度
        return jsonify({'task_id': task_id})


# 定义后台异步任务处理函数（≈ @Async 方法），由线程池 executor 调用，参数是任务编号和请求数据
def _process_task(task_id, data):
    # 底层实现，不用看：logger.info 记录任务开始处理
    logger.info(f"准备处理任务{task_id}，任务数据：{data}，处理中......")
    # 用 try 从请求数据取前端参数，取不到就走异常分支
    try:
        # 取出用户需求文本
        query = data["query"]
        # 取出多轮对话历史
        contexts = data["contexts"]
        # 取出是否 Agent 模式的开关（True=选工具调接口，False=直接大模型对话）
        isCopilot = data["isCopilot"]
        # 取出是否携带上下文的开关
        isContext = data["isContext"]
        # 取出携带最近几条上下文
        contextNumber = data["contextNumber"]

        # 取 utils/config.py 的模型名配置（历史遗留：曾允许前端自带模型参数，已停用）
        curr_model_name = model_name
        # 取 .env 配置的模型温度
        curr_temperature = model_temperature
        # 取 .env 配置的模型 API 密钥
        curr_api_key = model_api_key
        # 取 .env 配置的模型接口地址
        curr_api_url = model_base_url

    # 取前端参数失败的异常分支（≈ catch Exception）
    except Exception as e:
        # 调用 TaskManager.update_task() 把任务标记为失败并写入 MongoDB
        taskManager.update_task(task_id, [], [], '获取前端参数失败！', "", True)
        # 底层实现，不用看：traceback.format_exc() 拼异常堆栈写错误日志
        logger.error(f"任务[{task_id}]获取前端参数失败: {e}\n{traceback.format_exc()}")
        # 返回 400：获取前端参数失败
        return jsonify({'error': '获取前端参数失败！'}), 400

    # 判断模式：isCopilot=False 走普通对话，不走工具编排
    if not isCopilot:
        # 创建大模型客户端 LargeLanguageModel（models 模块，走 OpenAI 兼容接口）
        llm = LargeLanguageModel(curr_api_url, curr_api_key)
        # 用 try 调大模型，异常时结果置空
        try:
            # 带上下文的多轮对话分支
            if isContext:
                # 调用 LargeLanguageModel.context_chat_completions()，把最近 contextNumber 条历史一起发给模型
                results = llm.context_chat_completions(contexts, curr_model_name, curr_temperature, model_top_p, contextNumber)
            # 单轮问答分支
            else:
                # 调用 LargeLanguageModel.chat_completions()，只发当前问题
                results = llm.chat_completions(query, curr_model_name, curr_temperature,model_top_p)
        # 调模型抛异常时忽略（≈ catch 后吞掉）
        except:
            # 结果置为空字符串
            results = ""
        # 判断模型是否返回了非空结果
        if results is not None and len(results) != 0:
            # 调用 TaskManager.update_task() 把结果写入 MongoDB，标记任务完成
            taskManager.update_task(task_id, [], [], results, "", True)
            # 返回节点/连线为空、只带文字结果（在线程里返回值会被忽略）
            return jsonify({"nodes": [], "edges": [], "systemOutput": results})
        # 模型没有输出内容的分支
        else:
            # 同样调用 TaskManager.update_task() 写入（空）结果并结束任务
            taskManager.update_task(task_id, [], [], results, "", True)
            # 返回 400：模型无输出
            return jsonify({"nodes": [], "edges": [], "systemOutput": results}), 400
    # isCopilot=True 的分支：走 Agent 任务编排模式
    else:
        # 底层实现，不用看：logger.info 记录 Agent 任务启动
        logger.info(f"Task[{task_id}] started successfully, Go on ===>")
    # 用 try 执行 Agent 编排主流程，失败走异常分支
    try:
        # 创建 ApiPlanningHub（apis/api_planning_hub.py）：AI 任务编排核心组件（≈ new 一个编排 Service）
        api_planning_hub = ApiPlanningHub(milvus_uri, model_path, milvus_db_name, curr_model_name,
                                        curr_temperature,model_top_p, mongo_host, mongo_db, mongo_port, topK,
                                        curr_api_url, curr_api_key)
        # 创建 GenerateTaskHub（tasks 模块）：负责把多轮上下文拼成请求文本
        generate_task_hub = GenerateTaskHub(curr_model_name, curr_temperature, model_top_p,
                                            curr_api_url, curr_api_key, mongo_host, mongo_db, mongo_port, milvus_uri, milvus_db_name)
        # 判断本次请求是否需要带上下文
        if isContext:
            # 历史条数不足指定数量的分支
            if len(contexts) < contextNumber:
                # 历史不够就全部带上
                target_contexts = contexts
            # 历史条数足够的分支
            else:
                # 列表切片（≈ subList）：只取末尾最近的 contextNumber 条
                target_contexts = contexts[len(contexts) - contextNumber:len(contexts)]
            # 调用 GenerateTaskHub.gen_context_request_task() 把上下文拼成一段请求文本
            target_query = generate_task_hub.gen_context_request_task(target_contexts)
        # 不带上下文的分支
        else:
            # 直接用用户原始问题作为目标任务
            target_query = query
        # ★调用 ApiPlanningHub.apis_planning() 执行任务编排主流程（拆任务→选工具→提参数→调接口→总结）
        api_planning_hub.apis_planning(target_query, task_id)
    # 编排过程抛异常的分支（≈ catch Exception）
    except Exception as e:
        # 底层实现，不用看：traceback.format_exc() 拼异常堆栈写错误日志
        logger.error(f"任务[{task_id}]处理失败: {e}\n{traceback.format_exc()}")
        # 调用 TaskManager.update_task() 把任务标记为失败并写入提示语
        taskManager.update_task(task_id, [], [], "任务处理失败，请联系你的系统管理员", "", True)
        # 返回 400：任务处理失败（在线程里返回值前端拿不到）
        return jsonify({'message': f"任务[{query}]处理失败，任务编号[{task_id}]，请联系你的系统管理员"}), 400

# 定义路由 /api_task_status（≈ @PostMapping）：查询任务进度/结果
@app.route('/api_task_status', methods=['POST'])
# 挂鉴权装饰器：校验 JWT 令牌和 get_task_status 权限
@require_permission
# 接口函数（权限名 = 函数名 get_task_status）：按 task_id 查任务状态
def get_task_status():
    # 下面 docstring 是 Swagger 接口文档，不用看
    """
        ---
        tags:
          - Task Management
        description:
          获取任务状态接口
        parameters:
          - name: body
            in: body
            required: true
            schema:
              id: Task Status Request Body
              required:
                - task_id
              properties:
                task_id:
                  type: string
                  description: 任务ID
                  required: true
        responses:
          200:
            description: 任务状态获取成功
            schema:
              id: Task Status Response
              properties:
                task:
                  type: object
                  description: 任务详情
                  properties:
                    task_id:
                      type: string
                      description: 任务ID
                    status:
                      type: integer
                      description: 任务状态
                    nodes:
                      type: array
                      items:
                        type: object
                      description: 节点列表
                    edges:
                      type: array
                      items:
                        type: object
                      description: 边列表
                    isSuccess:
                      type: string
                      description: 是否成功
                    systemOutput:
                      type: string
                      description: 系统输出
          400:
            description: 请求参数错误
            schema:
              id: Error Response
              properties:
                error:
                  type: string
                  description: 错误信息
          404:
            description: 任务未找到或仍在运行
            schema:
              id: Error Response
              properties:
                status:
                  type: string
                  description: 错误状态
        """
    # 调用 request.get_json() 解析请求体 JSON（≈ @RequestBody）
    data = request.get_json()
    # 请求体为空：返回 400
    if not data:
        # 返回错误响应：缺少查询参数
        return jsonify({'error': 'Missing query parameter'}), 400
    # 从请求体取出任务编号
    task_id = data['task_id']
    # 调用 TaskManager.get_task_by_id() 从 MongoDB 按 id 查任务
    task = taskManager.get_task_by_id(task_id)
    # 查到任务的分支
    if task is not None:
        # 调用 task.to_dict() 转成字典后返回任务详情（≈ Entity 转 VO）
        return jsonify({'task': task.to_dict()})
    # 没查到任务的分支（不存在或还在跑）
    else:
        # 返回 404：任务未找到或仍在运行
        return jsonify({'status': 'Task not found or still running'}), 404

# 程序启动入口：直接运行 python app.py 时才执行（≈ SpringBoot 的 main 方法）
if __name__ == '__main__':
    # 启动 Flask 服务：关调试模式、监听 0.0.0.0:5001（≈ 启动内嵌 Web 容器）
    app.run(debug=False, host='0.0.0.0', port=5001)
