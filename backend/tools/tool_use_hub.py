# tool_use_hub.py —— 工具调用中心：拼 URL、组参数，真正发 HTTP 请求调外部系统接口

# 第三方库 requests：导入 Response 响应对象（HTTP 响应封装，≈ ResponseEntity）
from requests import Response

# 从 entity/tool_entity.py 导入 Tool 实体（含 api_url/path/method/参数定义）
from entity import Tool
# 第三方库 requests：发 HTTP 请求用（≈ OkHttp / RestTemplate）
import requests
# 从 utils/__init__.py 取全局日志器和失败状态码常量
from utils import logger, RESPONSE_STATUS_CODE_ERROR
# 标准库 traceback：打印异常堆栈（≈ e.printStackTrace()）
import traceback
# 从 tools/tool_manager.py 导入工具管理器（文件末尾 __main__ 测试用）
from tools.tool_manager import ToolManager
# 从 utils/config.py 取 .env 里的 sim_api_key，发请求时放请求头做鉴权
from utils import sim_api_key


# 工具调用中心类：拿着工具元数据 + 参数值去调外部 HTTP 接口（≈ 外部接口 Client）
class ToolUseHub:
    """工具调用中心（类比 Java：一个专门调外部 HTTP 接口的 Client/Service）。"""

    # 构造方法：保存调用器名称
    def __init__(self, name):
        """
        构造方法（≈ Java 构造方法）。
        :param name: 调用器名称（目前仅做标识用）
        """
        # 保存调用器名称（self ≈ this）
        self.name = name
        # 重试次数配置（预留字段，暂未使用）
        self.retries = 3

    # 工具调用方法：拼 URL、组参数、加请求头，按 method 发一次真实 HTTP 请求
    def tool_use(self, tool: Tool, requestBody: dict):
        """
        工具调用方法。该方法根据提供的工具对象和请求参数，调用工具的 API 接口。
        如果工具对象的 API 接口为空，则返回 None。
        参数:
            tool (Tool): 工具对象，包含工具的 API 接口、方法、路径等信息。
            requestBody (dict): 请求参数，以字典形式表示。
        返回:
            requests.Response: 工具 API 接口的响应对象。

        执行流程：
        1. 拼接完整 URL（api_url + path）；
        2. 遍历参数定义，把 in_=="path" 的参数替换进 URL、in_=="query" 的参数挑出来，
           剩下的参数留在 requestBody 里当作 JSON 请求体；
        3. 加请求头（API Key、必要时加 content-type: application/json）；
        4. 按 method（GET/POST/PUT/DELETE...）发 HTTP 请求，四种参数组合各走一条调用；
        5. 记录剩余调用次数和状态码，返回 Response 对象。
        """
        # 初始化响应对象（默认给失败状态码，调用成功后会被真实响应覆盖）
        response = Response()
        # 给空响应对象设置失败状态码
        response.status_code = RESPONSE_STATUS_CODE_ERROR

        # try：网络请求可能失败，整体兜底
        try:
            # 拼完整请求地址 = 基础地址 + 路径（f"" ≈ String.format）
            url = f"{tool.api_url}{tool.path}"
            # 打印待调用的工具地址和参数日志
            logger.info(f"准备调用工具[{url}：{requestBody}]....")
            # 初始化 query 参数字典（URL ?key=value 形式）
            param_request = {}
            # 遍历工具的参数定义，按参数位置（in_）分流处理
            for param in tool.request_body:
                # 判断调用方是否传了该参数
                if param.name in requestBody:
                    # 判断参数位置是否路径参数
                    if param.in_ == "path":
                        # 把参数值替换进 URL 的 {xxx} 占位符
                        url = url.replace("{"+param.name+"}",str(requestBody[param.name]))
                        # 用完从请求体里删掉（dict.pop ≈ Map.remove）
                        requestBody.pop(param.name)
                    # 判断参数位置是否查询参数
                    elif param.in_ == "query":
                        # 挑出来放进 query 参数字典
                        param_request[param.name] = requestBody[param.name]
                        # 同样从请求体里删掉
                        requestBody.pop(param.name)

            # 创建请求头并塞入 API 密钥（headers ≈ HttpHeaders）
            headers = {"X-API-Key": sim_api_key}
            # 判断是否还有 JSON 请求体参数
            if len(requestBody.keys()) > 0:
                # 有请求体就加 content-type 头
                headers["content-type"] = "application/json"

            # 按"有无 JSON 请求体 / 有无 query 参数"分四种情况发请求
            if len(requestBody.keys()) == 0:
                # 判断是否也没有 query 参数
                if len(param_request.keys()) == 0:
                    # 无 query、无 body，直接发请求（requests.request ≈ RestTemplate 调外部接口）
                    response = requests.request(tool.method.upper(), url, headers=headers)
                # 有 query 走 else
                else:
                    # 只带 query 参数发请求
                    response = requests.request(tool.method.upper(), url,params=param_request, headers=headers)
            # 有 JSON 请求体走 else
            else:
                # 判断是否没有 query 参数
                if len(param_request.keys()) == 0:
                    # 只带 JSON body 发请求
                    response = requests.request(tool.method.upper(), url, json=requestBody, headers=headers)
                # query 和 body 都有走 else
                else:
                    # query + JSON body 都带上发请求
                    response = requests.request(tool.method.upper(), url, params=param_request,json=requestBody, headers=headers)

            # 从响应头取剩余调用次数，没有则显示 'N/A'（≈ response.getHeaders().getFirst(...)）
            remaining_calls = response.headers.get('X-Remaining-Calls', 'N/A')
            # 打印剩余调用次数日志
            logger.info(f"API 调用成功，剩余调用次数: {remaining_calls}")

            # 打印响应状态码日志
            logger.info(f"API调用返回状态码: {response.status_code}")
        # except：网络异常等兜底，返回默认失败响应（≈ catch）
        except Exception as e:
            # 打印错误日志（含异常堆栈）
            logger.error(f"调用工具[{url}：{requestBody}]失败: {e}\n{traceback.format_exc()}")
            # 返回默认失败响应
            return response

        # 返回真实调用得到的响应对象
        return response


# 直接运行本文件时走这里的本地测试入口（≈ Java main 方法）
if __name__ == "__main__":
    # 创建工具调用器
    toolUseHub = ToolUseHub("test")
    # 创建工具管理器，连本机 MongoDB 和 Milvus
    toolManager = ToolManager('localhost', "tools", 27017,"http://127.0.0.1:19530","tool_db")
    # 按 id 查工具并取第一个（列表下标从 0 开始，同 Java 数组）
    tool = toolManager.get_tools_by_ids([15])[0]
    # 真实调用该工具接口，传参 productId=2
    response = toolUseHub.tool_use(tool, {"productId": 2})
    # 打印响应结果
    logger.info(response)
