# user_entity.py —— 用户实体：定义 MongoDB user 集合的数据结构（≈ @Entity 用户表）

# 第三方库 mongoengine：Document 是实体基类，IntField/StringField/ListField 是字段类型（≈ JPA 字段注解）
from mongoengine import StringField, IntField, Document, ListField


# 用户实体类，对应 MongoDB 的 user 集合
class User(Document):
    """用户实体（对应 MongoDB 的 user 集合），≈ JPA 的 @Entity 用户表"""
    # 用户 ID（必填，由 counters 集合原子自增生成）；底层实现，不用看：mongoengine IntField ≈ @Column Integer
    user_id = IntField(required=True)
    # 用户名（唯一 + 必填，重复注册会被数据库拒绝）；底层实现，不用看：StringField(unique=True) ≈ 唯一索引列
    userName = StringField(unique=True, required=True)
    # 密码（必填，存 bcrypt 密文，绝不存明文）；底层实现，不用看：StringField ≈ @Column String
    password = StringField(required=True)
    # 权限名列表（如 ['login','mesh_query',...]，默认空列表）；底层实现，不用看：ListField ≈ List<String>
    user_authority = ListField(StringField(), default=[])
