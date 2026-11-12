# config.py —— 配置中心：读 .env 配置（数据库地址、模型密钥、采样参数），local_mode=1 时强制本地数据库

# 标准库 os：读环境变量（≈ System.getenv()）
import os
# 标准库 sys：用 sys.exit() 终止程序（≈ System.exit()）
import sys

# 第三方库 python-dotenv：把 .env 文件加载进环境变量（≈ Spring 读 application.yml）
from dotenv import load_dotenv

# 执行加载动作：.env 里的键值对全部进环境变量
load_dotenv()



# 读 .env 的 milvus_uri（取不到用默认值）：Milvus 连接地址，默认本机 19530 端口
milvus_uri = os.getenv("milvus_uri", "http://localhost:19530")
# 读 .env 的 milvus_db_name：Milvus 中使用的数据库/集合所在库名
milvus_db_name = os.getenv("milvus_db_name", "tool_db")
# 读 .env 的 model_top_p 并转 float：采样范围 top_p，越低回答越稳定
model_top_p = float(os.getenv("model_top_p", "0.01"))
# 读 .env 的 mongo_host：MongoDB 服务器 IP
mongo_host = os.getenv("mongo_host", "127.0.0.1")
# 读 .env 的 mongo_db：MongoDB 数据库名（里面存 user/task/tool 三张"表"）
mongo_db = os.getenv("mongo_db", "tools")
# 读 .env 的 mongo_port 并转 int：MongoDB 端口
mongo_port = int(os.getenv("mongo_port", "27017"))
# 读 .env 的 api_result_max_length 并转 int：接口返回结果最大保留字符数（超长会截断）
api_result_max_length = int(os.getenv("api_result_max_length", "30000"))
# 读 .env 的 api_result_max_threshold 并转 float：结果截断阈值
api_result_max_threshold = float(os.getenv("api_result_max_threshold", "0.1"))
# 读 .env 的 model_path：本地模型存放目录名
model_path = os.getenv("model_path", "model")
# 读 .env 的 model_name：使用的大模型名称（如 qwen-max / deepseek-v3）
model_name = os.getenv("model_name", "deepseek-v3")
# 读 .env 的 model_temperature 并转 float：回答随机性（温度），越低越稳定
model_temperature = float(os.getenv("model_temperature", "0.01"))
# 读 .env 的 topK 并转 int：向量检索一次召回的候选工具数量
topK = int(os.getenv("topK", "5"))
# 读 .env 的 model_api_key：大模型 API 密钥（可能没配，值为 None ≈ null）
model_api_key = os.getenv("model_api_key")
# 读 .env 的 model_base_url：大模型 API 访问地址（可能没配）
model_base_url = os.getenv("model_base_url")
# 读 .env 的 sim_api_key：平台分配的 API key（必填，缺失则程序退出）
sim_api_key = os.getenv("sim_api_key")
# 读 .env 的 SECRET_KEY：JWT 签名密钥（带默认值）；底层实现，不用看：JWT 靠它做 HMAC 签名防伪造
SECRET_KEY = os.getenv('SECRET_KEY', 'zhipocopilot@zhipo.com')
# 读 .env 的 JWT_ALGORITHM：JWT 签名算法；底层实现，不用看：HS256 = HMAC-SHA256 签名
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')

# 读 .env 的 local_mode 开关：1 = 强制本机数据库模式（坑点开关）
local_mode = int(os.getenv("local_mode", "1"))
# 判断 local_mode 是否为真（非 0 即真）
if local_mode:
    # local_mode=1 时强制改用本机 Milvus（localhost:19530），.env 里的 milvus_uri 被忽略
    milvus_uri = "http://localhost:19530"
    # local_mode=1 时强制改用本机 MongoDB 地址 127.0.0.1
    mongo_host = "127.0.0.1"
    # local_mode=1 时强制改用本机 MongoDB 端口 27112（注意不是 27017！）
    mongo_port = 27112
# 判断 model_api_key 是否没配
if  not model_api_key:
    # 没配则退而读系统环境变量 DASHSCOPE_API_KEY（阿里云百炼平台的密钥）
    model_api_key = os.getenv("DASHSCOPE_API_KEY")
# 判断 model_base_url 是否没配
if  not model_base_url:
    # 没配则用阿里云 dashscope 的 OpenAI 兼容地址兜底
    model_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 启动自检：判断三个关键配置是否齐全（and 要求三者都非空才通过）
if not (sim_api_key and  model_api_key and model_base_url):
    # 缺配置就打印提示信息
    print(f"缺乏必要的参数sim_api_key：{sim_api_key}、model_api_key：{model_api_key}、model_base_url：{model_base_url}，服务中止！")
    # 终止程序（≈ System.exit()）
    sys.exit()
