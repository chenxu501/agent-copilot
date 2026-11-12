# tasks/task_manager.py —— 任务管理：任务的增删改查，把调用链图写入 MongoDB task 表

# 标准库 uuid：生成任务唯一 ID（≈ UUID.randomUUID()）
import uuid
# 第三方 mongoengine：MongoDB 的 ORM，提供实体映射和查询（≈ JPA/Hibernate），星号导入全部公开成员
from mongoengine import *
# 标准库 threading：线程锁，保证共享数据操作线程安全（Lock ≈ ReentrantLock）
import threading
# 第三方 cachetools 的 TTLCache：带过期时间的本地缓存（≈ Caffeine/Guava Cache）
from cachetools import TTLCache

# 导入 entity 包的 Parameter、Tool、Task 实体类，Task 对应 MongoDB 里的 task 集合
from entity import Parameter, Tool, Task
# 导入 utils 包的日志对象
from utils import logger
# 标准库：异常堆栈格式化，出错时把调用栈写进日志（≈ e.printStackTrace()）
import traceback


# 任务持久化管理：围绕 Task 实体做新建/更新/查询（≈ Repository + Service）
class TaskManager:

    # 构造方法：建立 MongoDB 连接并创建并发控制用的锁（≈ 配置 DataSource + new ReentrantLock）
    def __init__(self, mongo_host, mongo_db, mongo_port):
        # 调用 mongoengine 的 connect() 建立 MongoDB 连接（≈ 配置数据源）
        self.mongoClient = connect(mongo_db, host=mongo_host, port=mongo_port)
        # 创建缓存操作互斥锁，保证多线程并发安全（≈ synchronized）
        self.cache_lock = threading.Lock()

    # 方法：新建一个任务写入 MongoDB，返回唯一任务编号 task_id
    def create_task(self):
        # 循环生成 id 直到唯一（UUID 碰撞概率极低，防万一）
        while True:
            # 标准库 uuid 生成任务 id 并转字符串（≈ UUID.randomUUID().toString()）
            task_id = str(uuid.uuid4())
            # 调用 mongoengine 的 Task.objects().first()，查库里是否已有同 id 任务（≈ repository.findByTaskId()）
            task = Task.objects(task_id=task_id).first()
            # 库里没有同 id 任务，说明 id 唯一，跳出循环
            if task is None:
                # 结束重试循环
                break
        # 创建 Task 实体对象（≈ new Task()）
        task = Task()
        # 设置任务编号字段
        task.task_id = task_id
        # 设置初始状态 0
        task.status = 0
        # 初始化连线列表为空
        task.edges = []
        # 初始化节点列表为空
        task.nodes = []
        # 设置初始输出文案
        task.systemOutput = "初始化任务"
        # 调用 mongoengine 的 save()，插入 MongoDB（≈ repository.save()）
        task.save()
        # 返回新任务编号
        return task_id

    # 方法：更新任务执行状态和调用链图（节点/边/输出文案），成功返回 task_id
    def update_task(self, task_id, nodes, edges, systemOutput, isSuccess, isEnd):
        # 用 try 包住更新流程，异常统一记日志返回 None（try/except ≈ try/catch）
        try:
            # 调用 mongoengine 的 Task.objects.get()，按 task_id 精确查询任务（查不到会抛异常）
            task = Task.objects.get(task_id=task_id)
            # 防御性判断：任务不存在则记警告并返回 None
            if not task:
                # 打警告日志：任务不存在
                logger.warning(f"任务[{task_id}]不存在")
                # 返回 None 表示更新失败（≈ null）
                return None

            # 打日志：记录本次要更新的节点、边、输出和状态信息
            logger.info(f"Updating task {task_id}: nodes={nodes}, edges={edges}, "
                        f"systemOutput={systemOutput}, isSuccess={isSuccess}, isEnd={isEnd}")
            # 任务结束分支：记录最终状态
            if isEnd:
                # 记录最终调用链状态文案
                task.isSuccess = isSuccess
                # status 置 -1 表示已完成
                task.status = -1
            else:
                # 中间进度分支：status 递增，前端据此看到进度在动
                task.status = task.status + 1
                # 状态文案标为"任务实时执行调用情况"
                task.isSuccess = "任务实时执行调用情况"

            # 回写流程图节点列表
            task.nodes = nodes
            # 回写流程图连线列表
            task.edges = edges
            # 回写给用户看的输出/总结文案
            task.systemOutput = systemOutput

            # 调用 mongoengine 的 save() 保存更新（≈ repository.save()，有主键则更新）
            task.save()

            # 成功：返回任务编号
            return task_id
        except Exception as e:
            # 底层实现，不用看：except ≈ catch(Exception e)，捕获异常写错误日志带堆栈
            logger.error(f"任务[{task_id}]保存失败: {e}\n{traceback.format_exc()}")
        # 失败兜底返回 None
        return None

    # 方法：按任务编号查询任务，返回 Task 对象，不存在或异常返回 None
    def get_task_by_id(self, task_id):
        # 用 try 包住查询流程，异常统一记日志返回 None
        try:
            # 调用 mongoengine 的 Task.objects.get()，按 task_id 精确查询
            task = Task.objects.get(task_id=task_id)
            # 任务不存在则记警告并返回 None
            if not task:
                # 打警告日志：任务不存在
                logger.warning(f"任务[{task_id}]不存在")
                # 返回 None（≈ null）
                return None
            # 返回查到的 Task 对象
            return task
        except Exception as e:
            # 底层实现，不用看：捕获异常写错误日志带堆栈
            logger.error(f"获取任务[{task_id}]失败: {e}\n{traceback.format_exc()}")
            # 异常时返回 None
            return None


# if __name__ == "__main__"：直接运行本文件时的本地测试（≈ Java 的 main 方法）
if __name__ == "__main__":
    # 创建 TaskManager 实例，连本地 MongoDB 的 tools 库
    taskManager = TaskManager('localhost', "tools", 27017)
    # 调用本类 create_task() 新建任务，拿到任务编号
    task_id = taskManager.create_task()
    # 打日志：打印新任务编号
    logger.info(task_id)
