# task_entity.py —— 任务实体：定义 MongoDB task 集合，记录一次 AI 任务的执行信息

# 第三方库 mongoengine：Document 实体基类和各字段类型（≈ JPA 字段注解）
from mongoengine import Document, StringField, ListField, DictField, IntField


# 任务实体类，一次 AI 任务执行对应一条记录（≈ @Entity 任务表）
class Task(Document):
    """任务实体（对应 MongoDB 的 task 集合），一次 AI 任务执行对应一条记录"""
    # 任务编号（字符串形式的 UUID，前端凭它轮询进度）
    task_id = StringField()
    # 任务状态/进度码（处理中/完成等，数字越大进度越靠后）
    status = IntField()
    # 流程图节点列表，每个元素是 dict（节点 id、名称、类型等），前端画图用
    nodes = ListField(DictField())
    # 流程图连线列表，每个元素是 dict（起点节点→终点节点），前端画图用
    edges = ListField(DictField())
    # 任务是否成功（用字符串记录，如 "True"/"False"）
    isSuccess = StringField()
    # 系统输出：给用户看的文字总结（或错误提示）
    systemOutput = StringField()

    # 把 Task 对象转成 dict，方便 jsonify 序列化返回前端（≈ Bean 转 Map）
    def to_dict(self):
        """将 Task 对象转换为字典"""
        # 按字段名组装字典返回（self ≈ this）
        return {
            'task_id': self.task_id,
            'status': self.status,
            'nodes': self.nodes,
            'edges': self.edges,
            'isSuccess': self.isSuccess,
            'systemOutput': self.systemOutput
        }
