# demo_run.py —— 端到端演示：注册/登录 → 提交自然语言需求 → 轮询 → 打印执行链路
#
# 前置：mock_server.py 与 app.py 都已启动，且已执行 seed_tools.py 导入工具数据
# 用法：python demo_run.py
#       python demo_run.py "帮我查一下订单1的信息"

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:5001"
MOCK = "http://127.0.0.1:8080"
USER = "demo"
PWD = "Demo@12345"
DEFAULT_QUERY = "帮我查一下订单3现在的状态，如果是待发货就更新为运输中"


def post(path, payload, token=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:200]}


def obtain_token():
    """先尝试注册，已存在就直接登录。"""
    post("/register_user", {"username": USER, "password": PWD, "confirm": PWD})
    status, data = post("/login_user", {"username": USER, "password": PWD})
    if status != 200:
        raise SystemExit("登录失败：%s" % data)
    return data["auth_data"]["token"]["access_token"]


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY

    # 先把 mock 数据恢复初始状态，保证同一段流程可以反复演示
    try:
        urllib.request.urlopen(MOCK + "/reset", timeout=5).read()
    except Exception:
        print("提示：mock_server 未启动，跳过数据重置\n")

    token = obtain_token()
    print("已登录，用户：%s\n" % USER)

    print("需求：%s\n" % query)
    status, data = post("/api_planning", {
        "query": query,
        "contexts": [],
        "isCopilot": True,
        "isContext": False,
        "contextNumber": 0,
    }, token)
    if status != 200:
        raise SystemExit("提交失败：%s" % data)

    task_id = data["task_id"]
    print("任务号：%s\n开始执行 ..." % task_id)

    task = None
    for i in range(90):
        time.sleep(2)
        _, data = post("/api_task_status", {"task_id": task_id}, token)
        task = data.get("task") or data
        if not isinstance(task, dict):
            continue
        if str(task.get("status")) == "2" or task.get("isEnd") is True:
            print("完成，耗时约 %d 秒\n" % ((i + 1) * 2))
            break
    else:
        raise SystemExit("超时，任务未在 180 秒内完成")

    nodes = task.get("nodes") or []
    print("执行链路（%d 步）：" % len(nodes))
    for node in nodes:
        print("\n  [%s] %s" % (node.get("id"), node.get("label")))
        print("    意图：%s" % str(node.get("task_description", "")).strip())
        print("    参数：%s" % node.get("params"))
        print("    返回：%s" % str(node.get("result"))[:200])

    print("\n最终输出：%s" % task.get("systemOutput"))


if __name__ == "__main__":
    main()
