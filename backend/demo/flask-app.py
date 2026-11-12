# flask-app.py —— 【不用学，学习示例，不参与运行】Flask 接口示例：情感分析 + 两个演示接口，自带 Swagger 文档页

# 导入 Flask 的应用、请求对象、json 响应工具（≈ Controller 那一套）
from flask import Flask, request, jsonify
# 导入 OpenAI 客户端 SDK，用来调通义千问
from openai import OpenAI
# 导入 json 库（原代码保留，实际没用到）
import json
# 导入 os 库（原代码保留，实际没用到）
import os
# 导入 flasgger，给接口自动生成 Swagger 文档页
from flasgger import Swagger, swag_from

# 导入模型密钥、地址、模型名的配置（≈ 读配置文件）
from utils import model_api_key, model_base_url, model_name

# 创建 Flask 应用（≈ SpringBoot 的启动类）
app = Flask(__name__)
# 给应用挂上 Swagger 文档能力
Swagger(app)
# 初始化 OpenAI 客户端（基于阿里 DashScope）
client = OpenAI(
    api_key=model_api_key,
    base_url=model_base_url
)

# 路由：POST /sentiment_analysis 做情感分析（≈ @PostMapping）
@app.route('/sentiment_analysis', methods=['POST'])
def mesh_query():
    """
        情感分析
        ---
        tags:
          - sentiment API
        description:
            情感分析接口，json格式
        parameters:
          - name: body
            in: body
            required: true
            schema:
              id: 情感分析body
              required:
                - query
              properties:
                query:
                  type: string
                  description: 分析语句.

        responses:
          200:
              description: 转化成功
              schema:
                type: object
                properties:
                  message:
                    type: string
        """
    # 取出请求体 json（≈ @RequestBody）
    data = request.get_json()
    # 校验：没传 json 或缺 query 字段就报 400
    if not data or 'query' not in data:
        # 返回错误响应（≈ ResponseEntity.badRequest()）
        return jsonify({'error': 'Missing query parameter'}), 400

    # 取出要分析的文本
    query = data['query']
    # 把用户文本和"请分析情感"的指令拼成提示词
    content = query + '''
            \n
        ------------------------
        请分析上述文本的情感
        请直接输出结果，不需要输出额外的解释 
    '''
    # 调大模型，出错接住不崩（try/except ≈ try/catch）
    try:
        # 发送对话请求给通义千问
        completion = client.chat.completions.create(
            model=model_name,
            temperature=0.6,
            messages=[
                {'role': 'user', 'content': content}
            ]
        )
        # 取回答文本并去掉首尾空白
        response_text = completion.choices[0].message.content.strip()
        # 返回分析结果
        return {"message":response_text}

    # 捕获调用失败的异常
    except Exception as e:
        # 把异常信息当消息返回
        return jsonify({'message': str(e)})

# 路由：GET /api 按 id 查数据（≈ @GetMapping）
@app.route('/api', methods=['GET'])
def get_data_index():
    """
    获取指定 ID 的数据
    这是一个带有路径参数的 GET 方法，用于根据 ID 返回特定数据。
    ---
    tags:
      - Sample API
    parameters:
      - name: item_id
        in: query
        type: string
        required: true
        description: 数据的唯一标识符
    responses:
      200:
        description: 成功返回指定 ID 的数据
        schema:
          type: object
          properties:
            message:
              type: string
      404:
        description: 未找到指定 ID 的数据
        schema:
          type: object
          properties:
            error:
              type: string
              example: Item not found
    """
    # 取查询参数 item_id（≈ @RequestParam）
    item_id  = request.args.get('item_id')
    # 只有 id 是 123 才有数据（写死的演示逻辑）
    if item_id == "123":
        # 造一条返回数据
        data = {"message": f"Data for item_id: {item_id}"}
    else:
        # 其它 id 返回 404
        return jsonify({"error": "Item not found"}), 404
    # 正常返回数据
    return jsonify(data)

# 路由：GET /api/data 返回固定样本数据（≈ @GetMapping）
@app.route('/api/data', methods=['GET'])
def get_data():
    """
    获取样本数据
    这是一个简单的 GET 方法，用于返回样本数据。
    ---
    tags:
      - Sample API
    responses:
      200:
        description: 成功返回样本数据
        schema:
          type: object
          properties:
            message:
              type: string
              example: This is a sample data response
    """
    # 造一条固定返回数据
    data = {"message": "This is a sample data response"}
    # 转成 json 响应返回
    return jsonify(data)

# 直接运行本文件才启动服务（≈ main 方法）
if __name__ == '__main__':
    # 打印 Swagger 文档页地址
    print("Swagger访问地址：http://127.0.0.1:5001/apidocs")
    # 启动 Flask 服务，监听 5001 端口
    app.run(debug=False, host='0.0.0.0', port=5001)
