# milvus_use.py —— 【不用学，学习示例，不参与运行】Milvus 向量库建库建表、插数据、向量检索的入门示例

# 导入 json（原代码保留，实际没用到）
import json
# 导入类型标注（原代码保留，实际没用到）
from typing import List

# 导入 numpy，用来生成随机向量
import numpy as np
# 导入 yaml（原代码保留，实际没用到）
import yaml
# 导入 pymilvus 的库操作、客户端、字段类型、连接（≈ JDBC 那一套）
from pymilvus import db, MilvusClient, DataType, connections
# 导入进度条工具（原代码保留，实际没用到）
from tqdm import tqdm

# 导入加载状态枚举，判断集合有没有载入内存
from pymilvus.client.types import LoadState
# 导入 URL 解析器，从连接地址里拆出主机和端口
from urllib.parse import urlparse

# 只有直接运行本文件才执行下面的演示（≈ main 方法入口）
if __name__ == "__main__":
    # Milvus 服务的连接地址
    uri = "http://localhost:19530"
    # 演示用的库名（≈ MySQL 的 database）
    db_name = "test_db_v1"
    # 演示用的集合名（≈ MySQL 的 table）
    collection_name = "test_collection_v1"
    # 把连接地址解析成 URL 对象
    url_parsed = urlparse(uri)
    # 用解析出的主机端口建立连接（≈ DriverManager.getConnection）
    conn = connections.connect(host=url_parsed.hostname, port=url_parsed.port)
    # 查看当前 Milvus 里已有哪些数据库
    databases = db.list_database()
    # 打印数据库列表
    print(databases)
    # 如果目标库不存在就建库
    if db_name not in databases:
        # 创建数据库
        db.create_database(db_name)
    # 创建 Milvus 客户端，指定连哪个库（≈ Connection）
    client = MilvusClient(
        uri=uri,
        db_name=db_name
    )

    # 创建集合的表结构 schema（≈ 写 CREATE TABLE 语句）
    schema = MilvusClient.create_schema(
        enable_dynamic_field=False
    )
    # 加一个 int64 的主键字段 id
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    # 加一个 1024 维的浮点向量字段，用来存向量
    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=1024)

    # 创建索引参数对象（建索引前的配置）
    index_params = MilvusClient.prepare_index_params()
    # 给向量字段加索引：内积距离 + FLAT 精确检索（参数是底层细节，不用看）
    index_params.add_index(
        field_name="embedding",
        metric_type="IP",
        index_type="FLAT",
        params={"nlist": 2048}
    )
    # 建集合前先保证同名集合不存在
    if collection_name in client.list_collections():
        # 已存在就先删掉旧的（≈ DROP TABLE）
        client.drop_collection(collection_name)

    # 正式创建集合，带上表结构和索引
    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params
    )

    # 准备一个列表装随机数据

    datas = []
    # 查询向量先置空（None ≈ null）
    query_array = None
    # 循环造 1000 条数据（≈ for (int i = 0; ...)）
    for i in range(1000):

        # 生成一条 1024 维的随机向量
        vectors_array = np.random.rand(1024)
        # 第一条留着当后面的查询向量
        if query_array is None:
            # 保存下来
            query_array = vectors_array
        # 把 id 和向量组装成一条记录
        datas.append({
            "id": i,
            "embedding": vectors_array
        })

    # 如果集合还没加载进内存，先加载
    if client.get_load_state(collection_name)['state'] == LoadState.NotLoad:
        # 加载集合到内存（查询前必须做）
        client.load_collection(collection_name)

    # 把 1000 条数据一次性插入
    client.insert(collection_name=collection_name, data=datas, batch_size=len(datas))

    # 再随机生成一个查询向量
    vectors_array = np.random.rand(1024)

    # 用这个向量做相似度检索（≈ 按相似度排序取前 100 条）

    response = client.search(
        collection_name=collection_name,
        data=[vectors_array.tolist()],
        search_params={
            "metric_type": "IP",
            "params": {"nprobe": 16},
        },
        limit=100,
        output_fields=["id"],
        consistency_level="Bounded",
    )
    # 声明一个列表收集结果里的文档
    docs = []
    # 打印原始检索结果
    print(response)
    # 外层遍历每批结果
    for res in response:
        # 内层遍历每条结果
        for result in res:
            # 取出这条的业务字段
            chunk = result["entity"]
            # 只留 id 组装成文档
            docs.append({
                "id": chunk["id"]
            })
    # 打印最终文档列表
    print(docs)
    # 打印当前所有数据库，验证前面建的库在
    print(db.list_database())
