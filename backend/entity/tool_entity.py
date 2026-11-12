# tool_entity.py —— 工具实体：定义 MongoDB tool 集合（Tool 工具 + Parameter 参数）

# 第三方库 mongoengine：EmbeddedDocument 内嵌对象基类、Document 实体基类和各字段类型（≈ JPA 字段注解）
from mongoengine import EmbeddedDocument, EmbeddedDocumentField, StringField, BooleanField, ListField, IntField, \
    Document


# 工具的单个请求参数，内嵌在 Tool.request_body 里（≈ @Embeddable）
class Parameter(EmbeddedDocument):
    """工具的单个请求参数（嵌入在 Tool.request_body 列表里），≈ @Embeddable 参数对象"""
    # 参数名（如 orderId）；底层实现，不用看：mongoengine StringField ≈ @Column String
    name = StringField()
    # 是否必填（True/False ≈ true/false）；底层实现，不用看：BooleanField ≈ Boolean
    required = BooleanField()
    # 参数类型（如 string / integer）；底层实现，不用看：StringField 存类型名文本
    type = StringField()
    # 参数格式补充（如 date-time，OpenAPI 规范的 format）；底层实现，不用看：StringField 存格式名文本
    format = StringField()
    # 参数描述（给大模型看的说明，帮助它提取参数）
    description = StringField()
    # 枚举可选值列表（如 ["运输中","已完成"]）；底层实现，不用看：ListField ≈ List<String>
    enum = ListField(StringField())
    # 参数取值（调用接口时填入的实际值）
    value = StringField()
    # 参数位置（query / body / path 等，OpenAPI 的 in；加下划线是因为 in 是 Python 关键字）
    in_ = StringField()

# 工具实体类，一个工具 = 一个可被 AI 调用的 API 接口（≈ @Entity 主表）
class Tool(Document):
    """工具实体（对应 MongoDB 的 tool 集合）：一个工具 = 一个可被 AI 调用的 API 接口"""
    # 工具 ID（整数编号，删除工具时按它来删）；底层实现，不用看：IntField ≈ @Column Integer
    tool_id = IntField()
    # 是否需要做提示注入安全校验（"查询/获取"只读接口为 False）
    isValidate = BooleanField()
    # 操作 ID（OpenAPI 里的接口唯一标识）
    operationId = StringField()
    # 人类可读的工具名称（展示给用户看）
    name_for_human = StringField()
    # 给大模型看的工具名称（模型按它识别工具）
    name_for_model = StringField()
    # 工具（接口）功能描述，AI 选工具主要靠这段文本的语义
    description = StringField()
    # API 主机地址（如 http://xxx:8080）
    api_url = StringField()
    # API 路径（如 /orders/{id}，与 api_url 拼成完整地址）
    path = StringField()
    # HTTP 请求方法（GET / POST / PUT / DELETE 等）
    method = StringField()
    # 请求参数列表，内嵌 Parameter 对象（≈ List<Parameter>）；底层实现，不用看：EmbeddedDocumentField 内嵌对象字段
    request_body = ListField(EmbeddedDocumentField(Parameter))
