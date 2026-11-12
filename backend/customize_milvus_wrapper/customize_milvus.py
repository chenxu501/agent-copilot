# customize_milvus.py —— 【不用学，当工具类用】Milvus 向量库操作封装：建集合、插向量、语义检索、删数据

# 导入 JSON 处理（本文件没直接用到，保留）
import json
# 导入类型标注 List（≈ List，仅标注不影响运行）
from typing import List

# 导入 YAML 解析（本文件没直接用到，保留）
import yaml
# 导入 Milvus 官方 SDK：连接、建表、字段类型等（≈ 数据库驱动）
from pymilvus import db, MilvusClient, DataType, connections, Collection
# 导入进度条工具，长循环显示进度
from tqdm import tqdm

# 导入工具实体类（≈ Java 的 POJO）
from entity import Parameter, Tool
# 导入远程转向量模型，把文本换成向量存进 Milvus
from models import RemoteEmbeddingModel
# 导入集合加载状态枚举，判断集合有没有进内存
from pymilvus.client.types import LoadState
# 导入 URL 解析工具，把连接串拆成 host/port
from urllib.parse import urlparse


# Milvus（向量库）操作封装类（≈ DAO/Mapper）
class CustomizeMilvus:

    # 构造方法：建立 Milvus 连接（≈ DriverManager.getConnection）
    def __init__(self, uri, db_name):
        """
        CustomerMilvus 类的初始化方法，用于初始化 Milvus 数据库连接。

        参数:
            uri (str): Milvus 数据库的连接 URI。
            db_name (str): Milvus 数据库的名称。
        """
        # 把连接串拆成 host/port
        url_parsed = urlparse(uri)
        # 建立底层连接
        conn = connections.connect(host=url_parsed.hostname, port=url_parsed.port)
        # 列出所有数据库（≈ show databases）
        databases = db.list_database()
        # 创建文本转向量模型，后面变向量用
        self.embeddingModel = RemoteEmbeddingModel()
        # 判断目标库存不存在
        if db_name not in databases:
            # 不存在就新建一个库
            db.create_database(db_name)
        # 创建 Milvus 客户端（≈ 拿到可复用的 DB 客户端）
        self.client = MilvusClient(
            uri=uri,
            db_name=db_name
        )



    # 列出所有集合（集合 ≈ 表）
    def list_collections(self, ):
        """
        列出所有集合。
        返回:
            list: 所有集合的名称列表。
        """
        # 返回全部集合名
        return self.client.list_collections()



    # 判断集合存不存在
    def has_collection(self, collection_name):
        """
        检查集合是否存在。
        参数:
            collection_name (str): 集合的名称。
        返回:
            bool: 如果集合存在则返回 True，否则返回 False。
        """
        # 判断表名在不在全部表里
        return collection_name in self.list_collections()



    # 把集合加载进内存，检索前必须先做
    def load_collection_into_memory(self, collection_name):
        """
        加载集合到内存。
        参数:
            collection_name (str): 集合的名称。
        返回:
            None
        """
        # 判断是不是还没加载（NotLoad）
        if self.client.get_load_state(collection_name)['state'] == LoadState.NotLoad:
            # 没加载就加载进内存
            self.client.load_collection(collection_name)


    # 创建集合：先定字段和索引再建表（≈ create table）
    def create_collection(self, collection_name):
        """
        创建集合。
        参数:
            collection_name (str): 集合的名称。
        返回:
            None
        """
        # 建表结构，不开动态字段
        schema = MilvusClient.create_schema(
            enable_dynamic_field=False
        )
        # 加主键列 tool_id（≈ PRIMARY KEY）
        schema.add_field(field_name="tool_id", datatype=DataType.INT64, is_primary=True)
        # 加向量列，1024 维浮点向量
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=1024)
        # 加工具描述文本列
        schema.add_field(field_name="operation_summary", datatype=DataType.VARCHAR, max_length=4096, description="工具名称")

        # 准备索引参数，加快检索（≈ 建索引）
        index_params = MilvusClient.prepare_index_params()
        # 给向量列建索引，用余弦相似度（底层实现，不用看：索引参数）
        index_params.add_index(
            field_name="embedding",
            metric_type="COSINE",
            index_type="AUTOINDEX"
        )
        # 按上面的结构和索引建集合
        self.client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params
        )


    # 批量插入向量数据，每 10 条攒一批
    def insert_embeddings(self, collection_name, embeddings, datas):
        """
        插入嵌入数据。
        参数:
            collection_name (str): 集合的名称。
            embeddings (list): 嵌入数据列表。
            datas (list): 原始数据列表。
        返回:
            None
        """
        # 先确保集合已加载
        self.load_collection_into_memory(collection_name)
        # 攒一小批再插，减少网络往返（≈ 批量提交）
        batch_datas = []
        # 把数据和向量配对逐条处理
        for data, embedding in tqdm(zip(datas, embeddings)):
            # 把向量塞进这条数据
            data['embedding'] = embedding
            # 攒进当前批
            batch_datas.append(data)
            # 判断攒没攒够 10 条
            if len(batch_datas) == 10:
                # 够了就批量插一次
                self.client.insert(collection_name=collection_name, data=batch_datas)
                # 清空当前批
                batch_datas = []
        # 判断还有没有不足 10 条的零头
        if batch_datas:
            # 零头也要插进去
            self.client.insert(collection_name=collection_name, data=batch_datas)
            # 清空当前批
            batch_datas = []

    # 删除整个集合，连表带数据一起删（≈ drop table）
    def drop_collection(self, collection_name):
        # 调客户端删除集合
        self.client.drop_collection(
            collection_name=collection_name
        )



    # 把工具列表存进指定集合
    def insert_tools(self, collection_name, tools: List[Tool]):
        """
        将工具信息列表存入指定的 Milvus 集合中。
        参数:
            collection_name (str): 集合的名称。
            tools (list): 工具对象列表。
        返回:
            None
        """
        # 判断表存不存在
        if not self.has_collection(collection_name):
            # 不存在就先建表
            self.create_collection(collection_name)
        # 把工具文本转成向量并拼好数据
        embeddings, datas = self.embed_chunked_data(tools)
        # 批量插入
        self.insert_embeddings(collection_name, embeddings, datas)


    # 把工具列表拆成"入库数据 + 向量"两部分
    def embed_chunked_data(self, tools: List[Tool]):
        """
        将工具信息列表转为嵌入数据
        参数:
            tools (list): 工具对象列表。
        返回:
            tuple: 包含嵌入数据和原始数据的元组。
        """
        # 存要入库的原始数据（≈ List<Map>）
        datas = []
        # 存要转成向量的文本
        chunk_texts = []
        # 逐个工具处理
        for tool in tools:
            # 拼一条入库记录
            new_data = {
                "tool_id": tool.tool_id,
                "operation_summary": f"{tool.operationId}: {tool.name_for_human}: {tool.description}",

            }
            # 收进原始数据
            datas.append(new_data)
            # 这段描述文本拿去转向量
            chunk_texts.append(new_data["operation_summary"])
        # 批量把文本转成向量
        embeddings = self.embeddingModel.get_batch_embeddings(chunk_texts)
        # 返回向量和原始数据
        return embeddings, datas


    # 按查询语句语义检索，返回命中的工具 id 列表
    def get_docs(self, collection_name, query, topk=5):
        """
        用于根据查询语句从指定的 Milvus 集合中获取相关文档的 ID。
        该函数接收一个查询语句、集合名称和返回文档数量，通过与 Milvus 数据库交互获取相关文档 ID。
        代码流程逻辑如下：
            1. 确保目标集合已加载到内存中，便于后续搜索操作。
            2. 对输入的查询语句进行嵌入处理，将其转换为向量表示。
            3. 使用转换后的查询向量在 Milvus 集合中进行搜索，设置搜索参数、返回结果数量等。
            4. 解析搜索结果，提取每个匹配文档的工具 ID。
            5. 将提取的工具 ID 收集到列表中并返回。
        参数:
            collection_name (str): 集合的名称。
            query (str): 查询语句。
            topk (int): 返回的文档数量。
        返回:
            list: 包含文档 ID 的列表。
        """
        # 先确保集合已加载
        self.load_collection_into_memory(collection_name)
        # 把查询语句转成向量
        query_embedding = self.embeddingModel.get_embedding(query)
        # 用查询向量做语义检索取 topk 条，带出 id 和描述字段（底层实现，不用看：检索参数）
        response = self.client.search(
            collection_name=collection_name,
            data=[query_embedding],
            search_params={
                "metric_type": "COSINE",
                "params": {"level": 1},
            },
            limit=topk,
            output_fields=["tool_id", "operation_summary"],
            consistency_level="Bounded",
        )
        # 存命中的工具 id
        docs = []
        # 外层遍历每个查询向量的结果
        for res in response:
            # 内层遍历该向量命中的每条记录
            for result in res:
                # 取出这条命中记录
                chunk = result["entity"]
                # 把工具 id 收进结果
                docs.append(int(chunk["tool_id"]))
        # 返回工具 id 列表
        return docs

    # 按工具 id 批量删除工具数据
    def delete_tools(self, tools: List[Tool]):
        # 存要删的主键 id
        ids = []
        # 逐个工具收集 id
        for tool in tools:
            # 收集要删的 id
            ids.append(tool.tool_id)
        # 按 id 批量删除（≈ delete by ids）
        self.client.delete(
            collection_name="tools",
            ids=ids
        )
    # 按 id 批量取工具记录（含 id 和描述文本）
    def get_all_entity(self,ids):
        # 查询指定 id 的记录
        entities = self.client.get(collection_name="tools",ids=ids,output_fields=["tool_id", "operation_summary"])
        # 返回记录列表（≈ List<Map>）
        return entities
