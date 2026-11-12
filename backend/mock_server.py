# mock_server.py —— 本地模拟「供应链管理系统」的工具服务，替代已失效的外部演示服务器
#
# 背景：api_data 里的 OpenAPI 文档指向 http://121.43.198.13:8080，该地址现在需要登录，
#       直接调用只会返回登录页 HTML，导致 Agent 的「结果总结」环节拿不到有效数据。
#       本文件用内存数据复刻那套接口，让整条链路可以离线跑通。
#
# 启动：python mock_server.py          （监听 127.0.0.1:8080）
# 说明：只做演示用，数据存在内存里，重启即重置。

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------- 内存数据 ----------------
# 数据结构集中在一处定义，/reset 接口可以把它们恢复成初始状态，
# 这样重复演示时不会被上一次调用的副作用影响。
_SEED = {
    "products": {
        1: {"productId": 1, "name": "工业轴承 A100", "price": 128.0, "stock": 320, "description": "标准型深沟球轴承"},
        2: {"productId": 2, "name": "液压阀 B220", "price": 460.0, "stock": 85, "description": "二位二通电磁阀"},
        3: {"productId": 3, "name": "伺服电机 C330", "price": 2350.0, "stock": 12, "description": "750W 交流伺服电机"},
    },
    "substitutes": {
        1: [{"productId": 4, "name": "工业轴承 A100S", "matchRate": 0.96}],
        2: [{"productId": 5, "name": "液压阀 B220S", "matchRate": 0.91}],
        3: [],
    },
    "suppliers": {
        101: {"supplierId": 101, "name": "华东精密供应链", "status": "正常", "region": "区域1"},
        102: {"supplierId": 102, "name": "北方工业物资", "status": "正常", "region": "区域2"},
        103: {"supplierId": 103, "name": "南方物流集团", "status": "停用", "region": "区域1"},
    },
    "orders": {
        1: {"orderId": 1, "status": "待发货", "productId": 1, "supplierId": 101, "quantity": 20, "createTime": "2026-11-01 09:30:00"},
        2: {"orderId": 2, "status": "运输中", "productId": 2, "supplierId": 102, "quantity": 5, "createTime": "2026-11-03 14:10:00"},
        3: {"orderId": 3, "status": "待发货", "productId": 3, "supplierId": 101, "quantity": 2, "createTime": "2026-11-05 11:45:00"},
    },
}

PRODUCTS, SUBSTITUTES, SUPPLIERS, ORDERS = {}, {}, {}, {}
STATUS_FLOW = {"待发货": "运输中", "运输中": "已送达", "已送达": "已完成"}


def reset_data():
    """把四张内存表恢复成初始值（深拷贝，避免改到种子数据）。"""
    import copy
    global PRODUCTS, SUBSTITUTES, SUPPLIERS, ORDERS
    PRODUCTS = copy.deepcopy(_SEED["products"])
    SUBSTITUTES = copy.deepcopy(_SEED["substitutes"])
    SUPPLIERS = copy.deepcopy(_SEED["suppliers"])
    ORDERS = copy.deepcopy(_SEED["orders"])


reset_data()


def body():
    """兼容 JSON 请求体、表单和 query 参数三种取参方式。"""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {**request.args.to_dict(), **request.form.to_dict()}


def ok(data, message="success"):
    return jsonify({"code": 200, "message": message, "data": data})


def pick_int(src, *keys):
    for k in keys:
        if k in src and str(src[k]).strip() != "":
            try:
                return int(src[k])
            except (TypeError, ValueError):
                continue
    return None


# ---------------- 订单 ----------------
@app.route("/orders/getOrderByOrderId", methods=["POST"])
def get_order_by_id():
    oid = pick_int(body(), "orderId", "id")
    order = ORDERS.get(oid)
    return ok(order) if order else ok(None, "订单不存在")


@app.route("/orders/getByOrderStatus", methods=["POST"])
def get_orders_by_status():
    status = body().get("status") or body().get("orderStatus")
    return ok([o for o in ORDERS.values() if o["status"] == status])


@app.route("/orders/getOrdersBySupplierId", methods=["POST"])
def get_orders_by_supplier():
    sid = pick_int(body(), "supplierId")
    return ok([o for o in ORDERS.values() if o["supplierId"] == sid])


@app.route("/orders/getByProductId", methods=["POST"])
def get_orders_by_product():
    pid = pick_int(body(), "productId")
    return ok([o for o in ORDERS.values() if o["productId"] == pid])


@app.route("/orders/getByTimeRange", methods=["POST"])
def get_orders_by_time_range():
    src = body()
    start, end = str(src.get("startTime", "")), str(src.get("endTime", "9999"))
    return ok([o for o in ORDERS.values() if start <= o["createTime"] <= end])


@app.route("/orders/createOrder", methods=["POST"])
def create_order():
    src = body()
    oid = max(ORDERS) + 1
    ORDERS[oid] = {
        "orderId": oid,
        "status": src.get("status", "待发货"),
        "productId": pick_int(src, "productId"),
        "supplierId": pick_int(src, "supplierId"),
        "quantity": pick_int(src, "quantity") or 1,
        "createTime": src.get("createTime", "2026-11-10 20:00:00"),
    }
    return ok(ORDERS[oid], "创建成功")


@app.route("/orders/updateOrderStatus", methods=["PUT", "POST"])
def update_order_status():
    src = body()
    oid = pick_int(src, "orderId", "id")
    order = ORDERS.get(oid)
    if not order:
        return ok(None, "订单不存在")
    new_status = src.get("status") or src.get("orderStatus") or STATUS_FLOW.get(order["status"])
    if new_status not in list(STATUS_FLOW) + list(STATUS_FLOW.values()):
        return ok(None, "非法的订单状态：%s" % new_status)
    old = order["status"]
    order["status"] = new_status
    return ok(order, "订单 %d 状态已从「%s」更新为「%s」" % (oid, old, new_status))


@app.route("/orders/cancelOrder", methods=["DELETE", "POST"])
def cancel_order():
    oid = pick_int(body(), "orderId", "id")
    order = ORDERS.get(oid)
    if not order:
        return ok(None, "订单不存在")
    order["status"] = "已取消"
    return ok(order, "订单 %d 已取消" % oid)


# ---------------- 产品 ----------------
@app.route("/products/getProductById", methods=["POST"])
def get_product_by_id():
    pid = pick_int(body(), "productId", "id")
    return ok(PRODUCTS.get(pid))


@app.route("/products/getProductByName", methods=["POST"])
def get_product_by_name():
    name = str(body().get("name", ""))
    for p in PRODUCTS.values():
        if name and name in p["name"]:
            return ok(p)
    return ok(None, "产品不存在")


@app.route("/products/getBatchProductByProductIds", methods=["POST"])
def get_batch_products():
    src = body()
    ids = src.get("productIds") or src.get("ids") or []
    if isinstance(ids, str):
        ids = [int(x) for x in ids.replace("，", ",").split(",") if x.strip().isdigit()]
    return ok([PRODUCTS[i] for i in ids if i in PRODUCTS])


@app.route("/products/getProductSubstitutes", methods=["POST"])
def get_substitutes_by_id():
    pid = pick_int(body(), "productId", "id")
    return ok(SUBSTITUTES.get(pid, []))


@app.route("/products/getProductSubstitutesByName", methods=["POST"])
def get_substitutes_by_name():
    name = str(body().get("name", ""))
    for p in PRODUCTS.values():
        if name and name in p["name"]:
            return ok(SUBSTITUTES.get(p["productId"], []))
    return ok([], "产品不存在")


@app.route("/products/updateProductSubstitutes", methods=["POST"])
def update_substitutes():
    src = body()
    pid = pick_int(src, "productId")
    subs = src.get("substitutes") or src.get("substituteProducts") or []
    if pid is not None:
        SUBSTITUTES[pid] = subs
    return ok(SUBSTITUTES.get(pid, []), "替代产品已更新")


@app.route("/products/updateProductDescription", methods=["POST"])
def update_product_description():
    src = body()
    pid = pick_int(src, "productId", "id")
    product = PRODUCTS.get(pid)
    if not product:
        return ok(None, "产品不存在")
    product["description"] = src.get("description") or src.get("newDescription") or product["description"]
    return ok(product, "产品信息已更新")


@app.route("/products/addProduct", methods=["POST"])
def add_product():
    src = body()
    pid = max(PRODUCTS) + 1
    PRODUCTS[pid] = {
        "productId": pid,
        "name": src.get("name", "未命名产品"),
        "price": float(src.get("price", 0) or 0),
        "stock": pick_int(src, "stock") or 0,
        "description": src.get("description", ""),
    }
    return ok(PRODUCTS[pid], "添加成功")


@app.route("/products/removeProductById", methods=["DELETE", "POST"])
def remove_product_by_id():
    pid = pick_int(body(), "productId", "id")
    removed = PRODUCTS.pop(pid, None)
    return ok(removed, "删除成功" if removed else "产品不存在")


@app.route("/products/removeProductByName", methods=["DELETE", "POST"])
def remove_product_by_name():
    name = str(body().get("name", ""))
    for pid, p in list(PRODUCTS.items()):
        if name and name in p["name"]:
            PRODUCTS.pop(pid)
            return ok(p, "删除成功")
    return ok(None, "产品不存在")


# ---------------- 供应商 ----------------
@app.route("/suppliers/getSupplierById/<int:supplier_id>", methods=["GET"])
def get_supplier_by_id(supplier_id):
    return ok(SUPPLIERS.get(supplier_id))


@app.route("/suppliers/getSupplierByName", methods=["GET"])
def get_supplier_by_name():
    name = request.args.get("name", "")
    for s in SUPPLIERS.values():
        if name and name in s["name"]:
            return ok(s)
    return ok(None, "供应商不存在")


@app.route("/suppliers/getSupplierByStatus", methods=["GET"])
def get_supplier_by_status():
    status = request.args.get("status", "")
    return ok([s for s in SUPPLIERS.values() if s["status"] == status])


@app.route("/suppliers/querySuppliersByDeliveryRegion", methods=["POST"])
def query_suppliers_by_region():
    region = str(body().get("region", ""))
    return ok([s for s in SUPPLIERS.values() if s["region"] == region])


@app.route("/suppliers/addSuppliers", methods=["POST"])
def add_supplier():
    src = body()
    sid = max(SUPPLIERS) + 1
    SUPPLIERS[sid] = {
        "supplierId": sid,
        "name": src.get("name", "未命名供应商"),
        "status": src.get("status", "正常"),
        "region": src.get("region", "区域1"),
    }
    return ok(SUPPLIERS[sid], "添加成功")


@app.route("/suppliers/deleteSupplierById", methods=["DELETE", "POST"])
def delete_supplier_by_id():
    sid = pick_int(body(), "supplierId", "id")
    removed = SUPPLIERS.pop(sid, None)
    return ok(removed, "删除成功" if removed else "供应商不存在")


@app.route("/suppliers/deleteSupplierByName", methods=["DELETE", "POST"])
def delete_supplier_by_name():
    name = str(body().get("name", ""))
    for sid, s in list(SUPPLIERS.items()):
        if name and name in s["name"]:
            SUPPLIERS.pop(sid)
            return ok(s, "删除成功")
    return ok(None, "供应商不存在")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "orders": len(ORDERS), "products": len(PRODUCTS), "suppliers": len(SUPPLIERS)})


@app.route("/reset", methods=["POST", "GET"])
def reset():
    """恢复初始数据，方便反复演示同一段流程。"""
    reset_data()
    return jsonify({"code": 200, "message": "数据已重置", "data": {"orders": len(ORDERS)}})


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8080)
