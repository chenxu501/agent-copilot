# seed_tools.py —— 把 OpenAPI 文档里的接口解析成「工具」，写入 MongoDB 与 Milvus
#
# 用法：
#   python seed_tools.py            # 增量导入
#   python seed_tools.py --reset    # 先清空再导入
#
# 为什么不用 /upload_tool 接口：该接口要求 upload_file 权限，新注册用户默认没有
# （默认权限只有 login / logout / mesh_query / get_task_status），本地初始化数据直接调
# ToolManager 更省事，也避免脚本里维护一个登录态。

import sys
import time
import argparse

from utils import config
from tools import ToolManager

DATASET = r"api_data\dataset_apis_local.json"


def reset():
    """清空 MongoDB 的 tool 集合和 Milvus 的 tools 集合，避免重复导入。"""
    from pymongo import MongoClient
    from pymilvus import connections, utility
    from entity.tool_entity import Tool

    client = MongoClient(config.mongo_host, int(config.mongo_port))
    name = Tool._get_collection_name()
    deleted = client[config.mongo_db][name].delete_many({}).deleted_count
    print("  MongoDB 集合 %s 清理 %d 条" % (name, deleted))

    connections.connect(alias="seed", host="127.0.0.1", port="19530", timeout=20)
    if "tools" in utility.list_collections(using="seed"):
        utility.drop_collection("tools", using="seed")
        print("  Milvus 集合 tools 已删除")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="导入前先清空旧数据")
    parser.add_argument("--file", default=DATASET, help="OpenAPI 文档路径")
    args = parser.parse_args()

    print("目标库：MongoDB %s:%s / Milvus %s" % (config.mongo_host, config.mongo_port, config.milvus_uri))

    if args.reset:
        print("清理旧数据 ...")
        reset()

    manager = ToolManager(config.mongo_host, config.mongo_db, config.mongo_port,
                          config.milvus_uri, config.milvus_db_name)

    start = time.time()
    tools = manager.upload_file(args.file)
    count = len(tools) if tools else 0
    print("导入完成：%d 个工具，耗时 %.1fs" % (count, time.time() - start))
    print("可以用 python demo_run.py 验证整条链路")


if __name__ == "__main__":
    sys.exit(main())
