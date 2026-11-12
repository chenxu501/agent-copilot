# tool_manager.py —— 工具总管：工具的增删查、上传 OpenAPI JSON 解析，同时写 MongoDB 和 Milvus

# 标准库 json：解析/生成 JSON（≈ Jackson）
import json
# 标准库 time：时间工具，文件末尾测试代码 sleep 用（≈ Thread.sleep）
import time
# 标准库 typing：类型注解 List（≈ Java 泛型 List<Tool>），仅做类型提示
from typing import List

# 第三方库 mongoengine：MongoDB 的 ODM，星号导入其全部公开成员（≈ JPA/Hibernate）
from mongoengine import *
# 标准库 threading：线程锁工具，保护缓存并发读写（≈ ReentrantLock）
import threading
# 第三方库 cachetools：TTLCache 带过期时间的本地缓存（≈ Caffeine）
from cachetools import TTLCache
# 第三方库 yaml：YAML 解析库（本文件暂未实际使用）
import yaml
# 从 utils/__init__.py 取全局日志器和 .env 里的模型 API Key 配置
from utils import logger, model_api_key

# 从 customize_milvus_wrapper/customize_milvus.py 导入自封装的 Milvus 向量库客户端（≈ 向量库 DAO）
from customize_milvus_wrapper import CustomizeMilvus
# 从 entity/tool_entity.py 导入 Parameter、Tool 实体类（≈ domain 实体）
from entity import Parameter, Tool

# 从 models/qwen_reranker_model.py 导入千问重排序模型的单例工厂方法（用于检索结果精排）
from models.qwen_reranker_model import get_qwen_reranker_instance
# 标准库 os：读环境变量、文件路径
import os
# 第三方库 mongoengine 的连接管理三件套：建连/断连/取当前连接
from mongoengine import connect, disconnect, get_connection
# 第三方库 python-dotenv：把 .env 文件加载进环境变量
from dotenv import load_dotenv
# 执行加载动作：本模块被导入时立即生效
load_dotenv()


# 工具管理器类：围绕 Tool 实体做增删查 + 缓存 + 向量检索（≈ DAO/Repository）
class ToolManager:
    """工具管理器（类比 Java：Tool 的 DAO/Repository + 缓存 + 检索服务）。"""

    # 构造方法：建 MongoDB 连接、初始化缓存锁、Milvus 客户端和重排序模型
    def __init__(self, mongo_host, mongo_db, mongo_port, milvus_uri, milvus_db_name):
        """
        构造方法（≈ Java 构造方法）：建 MongoDB 连接、初始化缓存锁、Milvus 客户端和重排序模型。
        :param mongo_host: MongoDB 主机
        :param mongo_db: MongoDB 数据库名
        :param mongo_port: MongoDB 端口
        :param milvus_uri: Milvus 连接地址
        :param milvus_db_name: Milvus 数据库/集合名
        """
        # try：先检查是否已有 MongoDB 连接，有就断开避免重复建连
        try:
            # 调用 mongoengine 的 get_connection() 取当前连接对象
            existing_connection = get_connection()
            # 判断是否真有旧连接（对象非空 ≈ != null）
            if existing_connection:
                # 调用 mongoengine 的 disconnect() 断开旧连接（≈ 重建 DataSource 前先关旧的）
                disconnect()
        # except：检查连接出异常时只告警不中断（≈ catch）
        except Exception as e:
            # 记录告警日志后继续，用下面新建的连接
            logger.warning(f"检查ToolManager的已有MongoDB连接: {e}，已重建连接 。")
        # 调用 mongoengine 的 connect() 建立 MongoDB 连接（≈ DriverManager.getConnection）
        self.mongoClient = connect(mongo_db, host=mongo_host, port=mongo_port)
        # 保存数据库名称，后面 get_next_tool_id 取库用
        self.db_name = mongo_db
        # 创建缓存互斥锁，保证多线程读写缓存安全（≈ ReentrantLock）
        self.cache_lock = threading.Lock()
        # 创建工具缓存：最多 100 条、3600 秒过期（≈ Caffeine Cache）
        self.tool_cache = TTLCache(maxsize=100, ttl=3600)
        # 调用 customize_milvus_wrapper/customize_milvus.py 创建 Milvus 向量库客户端
        self.milvus = CustomizeMilvus(milvus_uri, milvus_db_name)
        # 判断 .env 里是否配了模型 API Key
        if model_api_key:
            # 调用 models/qwen_reranker_model.py 初始化千问重排序模型（对检索结果精排）
            self.reranker = get_qwen_reranker_instance(model_api_key)
        # 没配 Key 走 else 分支直接报错
        else:
            # raise 抛参数异常，提示先配置环境变量（≈ throw new IllegalArgumentException）
            raise ValueError("请设置model_api_key环境变量")

    # 删除全部工具：MongoDB 文档、Milvus 向量、本地缓存三处一起清
    def delete_all_tools(self):
        """
        工具删除方法。该方法根据提供的工具 ID，从数据库中删除对应的工具。
        如果工具 ID 为空，则返回 None。
        参数:
            tool_id (int): 工具 ID，用于唯一标识要删除的工具。
        返回:
            None
        """
        # 调用 entity/tool_entity.py 的 Tool 实体，清空 MongoDB 全部工具文档（≈ repository.deleteAll()）
        Tool.objects.delete()
        # 调用 customize_milvus_wrapper/customize_milvus.py 的 CustomizeMilvus.drop_collection()，删掉向量集合
        self.milvus.drop_collection(collection_name="tools")
        # 调本类 clear_cache() 清空本地缓存，防止读到已删工具
        self.clear_cache()

    # 查询全部工具，返回 mongoengine 原始查询集
    def get_raw_all_tools(self):
        """查询全部工具（原始 mongoengine 查询集，不做任何包装）。
        :return: 全部 Tool 对象（≈ repository.findAll()）"""
        # 调用 entity/tool_entity.py 的 Tool 实体查全部文档（≈ repository.findAll()）
        return Tool.objects.all()

    # 查询全部工具并整理成给前端/LLM 看的扁平字典列表
    def get_all_tools(self):
        """查询全部工具并整理成"给前端/LLM 看"的扁平字典列表（含参数 JSON 串）。
        :return: list[dict] —— 每个元素含 key/index/name/description/params/method"""
        # 查 MongoDB 全部工具文档
        tools = Tool.objects.all()
        # 收集整理好的字典列表
        results = []
        # 序号计数器，给前端列表排序用
        index = 1
        # 遍历每个工具
        for tool in tools:
            # 收集该工具的参数定义列表
            arguments = []
            # 遍历工具的每个请求参数
            for chat_parameter in tool.request_body:
                # 把参数整理成 name/description/schema 三段结构
                arguments.append({
                    "name": chat_parameter.name,
                    "description": chat_parameter.description,
                    "schema": {
                        "type": chat_parameter.type,
                        "format": chat_parameter.format,
                        "enum": chat_parameter.enum,
                    }
                })
            # 调标准库 json.dumps 把参数列表转 JSON 字符串（ensure_ascii=False 中文不转义）
            requestBody = json.dumps(arguments, ensure_ascii=False)
            # 组装一条给前端/LLM 看的工具摘要字典
            results.append({
                "key": tool.tool_id,
                "index": index,
                "name": tool.name_for_human,
                "description": tool.description,
                "params": requestBody,
                "method": tool.method
            })
            # 序号加一
            index += 1
        # 返回整理好的工具摘要列表
        return results

    # 按 id 列表批量删除工具（MongoDB + Milvus + 本地缓存一起删）
    def delete_tools(self,tool_ids):
        """按 id 列表批量删除工具（MongoDB 文档 + Milvus 向量 + 本地缓存一起删）。
        :param tool_ids: list —— 要删除的工具 id 列表
        :return: None"""
        # 先查出工具对象，删 Milvus 需要工具详情
        tools = self.get_tools_by_ids(tool_ids)
        # 遍历要删除的工具逐个删 MongoDB 文档
        for tool in tools:
            # 调用 entity/tool_entity.py 的 Tool 实体按 tool_id 删文档（≈ repository.deleteById）
            Tool.objects(tool_id=tool.tool_id).delete()
        # 调用 customize_milvus_wrapper/customize_milvus.py 的 CustomizeMilvus.delete_tools() 同步删向量
        self.milvus.delete_tools(tools)
        # 清空本地缓存
        self.clear_cache()


    # 用 MongoDB 原子自增生成下一个工具 id，保证并发下不重复
    def get_next_tool_id(self):
        """用 MongoDB 的原子自增操作（findAndModify）生成下一个工具 id（避免并发重复）。
        :return: int —— 自增后的新 id"""
        # 按名字取数据库对象（≈ mongoClient.getDatabase(dbName)）
        db = self.mongoClient[self.db_name]
        # 调 findOneAndUpdate 原子自增 counters 集合的 sequence_value（$inc ≈ 数据库 sequence）
        counter = db.mongoClient.counters.find_one_and_update(
            {"_id": "tool_id"},
            {"$inc": {"sequence_value": 1}},
            upsert=True,
            return_document=True
        )
        # 返回自增后的值作为新工具 id
        return counter["sequence_value"]

    # 批量插入工具：分配自增 id -> 存 MongoDB -> 描述向量写 Milvus
    def insert_tools(self, tools: List[Tool]):
        """批量插入工具：给每个工具分配自增 id -> 存 MongoDB -> 向量写入 Milvus。
        :param tools: List[Tool] —— 待入库的工具列表
        :return: 入库的工具列表"""
        # 收集真正入库的工具列表
        new_tools = []
        # 遍历待入库的每个工具
        for tool in tools:
            # 调本类 get_next_tool_id() 分配自增 id
            tool.tool_id = self.get_next_tool_id()
            # 调用 entity/tool_entity.py 的 Tool 实体保存进 MongoDB（≈ JPA save）
            tool.save()
            # 加入入库结果列表
            new_tools.append(tool)
        # 调用 customize_milvus_wrapper/customize_milvus.py 的 CustomizeMilvus.insert_tools()，把工具描述转向量写入 Milvus 供语义检索
        self.milvus.insert_tools("tools", new_tools)

        # 返回入库的工具列表
        return tools

    # 清空工具本地缓存（多线程安全）
    def clear_cache(self):
        """
        工具缓存清除方法。该方法清除工具缓存中的所有工具。
        """
        # with 加锁进临界区，退出自动释放（≈ synchronized）
        with self.cache_lock:
            # 取出缓存里全部 key
            tool_ids = self.tool_cache.keys()
            # 遍历逐个删除
            for tool_id in tool_ids:
                # pop 从缓存移除；第二参数 None 表示 key 不存在也不报错
                self.tool_cache.pop(tool_id, None)


    # 按 id 列表逐个查 MongoDB 取工具对象（不走缓存）
    def get_tools_by_ids_from_mongo(self, tool_ids: List[int]):
        """
        工具 ID 列表查询方法。该方法根据提供的工具 ID 列表，从数据库中查询对应的工具对象。
        如果工具 ID 列表为空，则返回空列表。
        参数:
            tool_ids (List[int]): 工具 ID 列表，用于唯一标识要查询的工具。
        返回:
            List[Tool]: 工具对象列表。
        """
        # 收集查到的工具
        tools = []
        # 遍历每个工具 id
        for tool_id in tool_ids:
            # try：精确查询，查不到会抛异常
            try:
                # 调用 entity/tool_entity.py 的 Tool 实体按 tool_id 精确查询（≈ repository.findByToolId）
                tool = Tool.objects.get(tool_id=tool_id)
                # 查到就加入列表
                tools.append(tool)
            # except：查不到该 id 时记日志跳过（bare except ≈ catch 所有异常）
            except:
                # 记录告警日志
                logger.warning(f"工具 [ {tool_id} ] 不存在.")
                # continue 跳过本次循环，处理下一个 id
                continue
        # 返回查到的工具列表（查不到的 id 自动缺席）
        return tools



    # 按 id 列表查工具（带 TTL 缓存：命中直接用，未命中回源 MongoDB 并回填）
    def get_tools_by_ids(self, tool_ids: List[int]) -> List[Tool]:
        """
        工具 ID 列表查询方法（带缓存：命中缓存直接用，未命中回源 MongoDB 并回填缓存）。
        该方法根据提供的工具 ID 列表，从数据库中查询对应的工具对象。
        如果工具 ID 列表为空，则返回空列表。
        参数:
            tool_ids (List[int]): 工具 ID 列表，用于唯一标识要查询的工具。
        返回:
            List[Tool]: 工具对象列表。
        """
        # 判断 id 列表是否为空
        if len(tool_ids) == 0:
            # 空列表直接返回空结果
            return []
        # with 加锁读缓存，保证并发安全
        with self.cache_lock:
            # 列表推导式批量取缓存（≈ stream().map().collect(toList())）
            cached_tools = [self.tool_cache.get(pid) for pid in tool_ids]

        # 找出缓存未命中的 id（zip 并行遍历两个列表）
        missing_tool_ids = [tool_id for tool_id, tool in zip(tool_ids, cached_tools) if tool is None]
        # 过滤掉未命中的空值，只留命中的工具
        cached_tools = [tool for tool in cached_tools if tool is not None]
        # 判断是否存在未命中的 id
        if missing_tool_ids:
            # 未命中的回源 MongoDB 批量查询
            data = self.get_tools_by_ids_from_mongo(missing_tool_ids)
            # 遍历查回来的工具
            for tool in data:
                # with 加锁写缓存
                with self.cache_lock:
                    # 回填缓存（≈ cache.put(key, value)）
                    self.tool_cache[tool.tool_id] = tool

                # 同时追加进结果列表
                cached_tools.append(tool)
        # 返回"缓存命中 + 回源查到"的全部工具
        return cached_tools



    # 按 operationId 列表查工具（不走缓存，直接查 MongoDB）
    def get_tools_by_operationIds(self, operationIds) -> List[Tool]:
        """
        工具 operationId 列表查询方法。该方法根据提供的工具 operationId 列表，从数据库中查询对应的工具对象。
        如果工具 operationId 列表为空，则返回空列表。
        参数:
            operationIds (List[int]): 工具 operationId 列表，用于唯一标识要查询的工具。
        返回:
            List[Tool]: 工具对象列表。
        """
        # 收集查到的工具
        tools = []
        # 遍历每个 operationId
        for operationId in operationIds:
            # try：精确查询，查不到抛异常
            try:
                # 调用 entity/tool_entity.py 的 Tool 实体按 operationId 精确查询
                tool = Tool.objects.get(operationId=operationId)
                # 查到就加入列表
                tools.append(tool)
            # except：查不到就记日志跳过
            except:
                # 记录提示日志
                logger.info(f"User with id {operationId} does not exist.")
                # continue 跳过本次循环
                continue
        # 返回查到的工具列表
        return tools



    # 解析上传的 OpenAPI/Swagger JSON 文件，转成 Tool 列表入库
    def upload_file(self, filename):
        """
        工具文件上传方法。该方法根据提供的工具文件，将工具上传到数据库中。
        如果工具文件为空，则返回 None。
        参数:
            filename (str): 工具文件路径（OpenAPI/Swagger 格式的 JSON 文档）。
        返回:
            解析并入库后的 Tool 对象列表。

        解析流程：
        1. 读 JSON 文件，取出 components.schemas（JSON Schema 定义）和服务器基础地址 servers[0].url；
        2. 遍历 paths 里每个接口（path + method），从路径里截出 operationId；
        3. 解析 parameters（path/query 参数）和 requestBody（JSON 请求体参数）生成 Parameter 列表；
        4. 组装 Tool 对象（"查询/获取"类接口标记 isValidate=False，免做注入校验）；
        5. insert_tools 入库（MongoDB + Milvus 向量）。
        """
        # with 打开 JSON 文件，退出自动关文件流（≈ try-with-resources）
        with open(filename, 'r', encoding='utf-8') as file:
            # 调标准库 json.load 把文件内容解析成 dict（≈ ObjectMapper.readValue）
            data = json.load(file)
            # 取出 components.schemas 数据模型定义映射表
            schemas = data["components"]["schemas"]

        # 收集解析出的工具列表
        tools = []
        # 取外部系统基础地址 servers[0].url（如 http://xxx/api）
        url = data["servers"][0]["url"]
        # 接口计数器，给工具编号用
        index = 0
        # 遍历文档里所有接口路径
        for path in data["paths"]:
            # 同一路径可能有 get/post 等多个方法，逐个遍历
            for method in data["paths"][path]:
                # 计数器加一
                index += 1
                # 取出该接口的文档信息
                api_information = data["paths"][path][method]
                # 按 / 把路径切成多段（≈ String.split("/")）
                operationIds = path.split('/')
                # 从路径末尾往前找第一段不含 {} 的，定为 operationId
                for i in range(len(operationIds)):
                    # 判断该段是否路径参数占位符 {id} 之类
                    if "{" in operationIds[len(operationIds) - 1 - i] and "}" in operationIds[
                        len(operationIds) - 1 - i]:
                        # 是占位符就 continue 跳过，继续往前找
                        continue
                    # 不是占位符走 else
                    else:
                        # 把该段定为 operationId
                        operationId = operationIds[len(operationIds) - 1 - i]
                        # break 跳出循环，找完即止
                        break
                # 取接口中文名 summary
                name_for_human = api_information["summary"]
                # 生成给模型看的代号 tool1、tool2……
                name_for_model = "tool" + str(index)

                # 取接口描述文本
                description = api_information["description"]
                # 初始化参数列表，收集该接口全部参数定义
                params = []
                # 判断文档里是否定义了 URL 参数（path/query）
                if "parameters" in api_information:
                    # 取参数定义列表
                    requestParams = api_information["parameters"]
                    # 遍历每个参数
                    for param in requestParams:
                        # 取参数名
                        param_name = param["name"]
                        # 取参数描述
                        param_description = param["description"]
                        # 取参数位置：path / query / header……
                        in_ = param["in"]
                        # 类型映射：string/array 直接取，否则取 format（如 int64/double）
                        if param["schema"]["type"] == "string":
                            # 标记类型为 string
                            paramType = "string"
                        # 判断是否数组类型
                        elif param["schema"]["type"] == "array":
                            # 标记类型为 array
                            paramType = "array"
                        # 其他数值类型走 else
                        else:
                            # 取 format 当类型（int64/double 等）
                            paramType = param["schema"]["format"]
                        # 初始化枚举值列表
                        enum = []
                        # 判断参数 schema 里是否定义了枚举
                        if "enum" in param["schema"]:
                            # 取出枚举值列表
                            enum = param["schema"]["enum"]

                        # 参数默认按必填处理
                        required = True
                        # 调用 entity/tool_entity.py 的 Parameter 实体组装参数（≈ new Parameter(...)）
                        parameter = Parameter(
                            name=param_name,
                            type=paramType,
                            description=param_description,
                            enum=enum,
                            required=required,
                            in_=in_

                        )
                        # 加入参数列表
                        params.append(parameter)

                # 判断文档里是否定义了 JSON 请求体
                if "requestBody" in api_information:
                    # 从 $ref 引用里截出 Schema 名，再查 schemas 拿字段定义
                    requestBody = \
                        api_information["requestBody"]["content"]["application/json"]["schema"]["$ref"].split('/')[-1]
                    # 查 schemas 映射表拿到请求体各字段定义
                    requestParams = schemas[requestBody]["properties"]
                    # 遍历请求体每个字段
                    for param in requestParams:
                        # 字段名就是 properties 的 key
                        param_name = param
                        # 取字段描述
                        param_description = requestParams[param]["description"]
                        # 类型映射：string/array 直接取，否则取 format
                        if requestParams[param]["type"] == "string":
                            # 标记类型为 string
                            paramType = "string"
                        # 判断是否数组类型
                        elif requestParams[param]["type"] == "array":
                            # 标记类型为 array
                            paramType = "array"
                        # 其他类型走 else
                        else:
                            # 取 format 当类型
                            paramType = requestParams[param]["format"]
                        # 初始化枚举值列表
                        enum = []
                        # 判断字段是否定义了枚举
                        if "enum" in requestParams[param]:
                            # 取出枚举值列表
                            enum = requestParams[param]["enum"]
                        # 判断字段是否定义了 format
                        if "format" in requestParams[param]:
                            # 有 format 就取它
                            format = requestParams[param]["format"]
                        # 没定义 format 走 else
                        else:
                            # 用类型名兜底当 format
                            format = paramType

                        # 判断是否有枚举值
                        if len(enum) != 0:
                            # 有枚举值的参数，格式标记为 enum
                            format = "enum"

                        # 参数默认按必填处理
                        required = True
                        # 调用 entity/tool_entity.py 的 Parameter 实体组装请求体参数
                        parameter = Parameter(
                            name=param_name,
                            type=paramType,
                            description=param_description,
                            enum=enum,
                            required=required,
                            format=format,
                            # 请求体参数固定标记为 requestBody
                            in_="requestBody"
                        )
                        # 加入参数列表
                        params.append(parameter)
                # 没有请求体走 else
                else:
                    # 请求参数列表置空
                    requestParams = []
                # 判断接口名是否"查询/获取"类（只读接口免做注入校验，其余增删改需要校验）
                if "查询" in name_for_human or "获取" in name_for_human:
                    # 只读接口不校验
                    isValidate = False
                # 非只读接口走 else
                else:
                    # 增删改接口需要校验
                    isValidate = True

                # 调用 entity/tool_entity.py 的 Tool 实体组装工具（≈ new Tool(...)）
                tool = Tool(
                    tool_id=index,
                    operationId=operationId,
                    name_for_human=name_for_human,
                    name_for_model=name_for_model,
                    description=description,
                    api_url=url,
                    isValidate=isValidate,
                    path=path,
                    method=method,
                    request_body=params

                )
                # 加入工具列表
                tools.append(tool)
        # 调本类 insert_tools() 批量入库（MongoDB + Milvus 向量）
        self.insert_tools(tools)
        # 返回解析出的工具列表
        return tools

    # 测试方法：按 id 从 Milvus 取原始实体（调试向量库用）
    def test_milvus(self,ids):
        """测试方法：按 id 从 Milvus 取原始实体（调试向量库用）。"""
        # 调用 customize_milvus_wrapper/customize_milvus.py 的 CustomizeMilvus.get_all_entity() 取原始向量实体
        return self.milvus.get_all_entity(ids)

    # 工具检索：向量召回 + 重排序精排两步走
    def search_tools_with_rerank(self, query, top_k=20, final_top_n=5):
        """
        使用重排序模型进行工具搜索（向量召回 + 精排两步走）
        Args:
            query (str): 查询文本
            top_k (int): 向量检索召回数量
            final_top_n (int): 最终返回结果数量
        Returns:
            list: 重排序后的工具列表
        """
        # 第一步：调用 CustomizeMilvus.get_docs() 做 Milvus 语义检索，召回候选工具 id
        candidate_tool_ids = self.milvus.get_docs("tools", query, topk=top_k)
        # 第二步：按 id 走缓存查 MongoDB，取候选工具详情
        candidate_tools = self.get_tools_by_ids(candidate_tool_ids)
        # 第三步：拼"名称: 描述"文本，供重排序模型打分
        candidates_for_rerank = [f"{tool.name_for_human}: {tool.description}" for tool in candidate_tools]
        # 第四步：调用 models/qwen_reranker_model.py 的重排模型，返回按相关度排好的下标顺序
        reranked_indices = self.reranker.rerank(query, candidates_for_rerank)
        # 第五步：按下标顺序重排候选工具
        final_tools = [candidate_tools[i] for i in reranked_indices]

        # 切片取前 N 个返回（≈ List.subList(0, n)）
        return final_tools[:final_top_n]

# 直接运行本文件时走这里的本地测试入口（≈ Java main 方法）
if __name__ == "__main__":
    # 创建 ToolManager，连本机 MongoDB 和 Milvus
    toolManager = ToolManager('localhost', "tools", 27017,"http://127.0.0.1:19530","tool_db")
    # 清空全部旧工具
    toolManager.delete_all_tools()
    # 解析 OpenAPI 文档并入库（MongoDB + Milvus）
    toolManager.upload_file("../api_data/dataset_apis.json")
    # 等 5 秒让向量写入生效（≈ Thread.sleep(5000)）
    time.sleep(5)

    # 查 MongoDB 全部工具
    tools = Tool.objects.all()
    # 遍历打印每个工具
    for tool in tools:
        # 打印工具 id 和名称
        logger.info(f"tool_id: {tool.tool_id}, tool_name: {tool.name_for_human}")

    # 按 operationId 查工具
    operation_tools = toolManager.get_tools_by_operationIds(["getByProductId"])
    # 打印查到的工具 id 和名称
    logger.info(f"Operation tool_id: {operation_tools[0].tool_id}, tool_name: {operation_tools[0].name_for_human}")
