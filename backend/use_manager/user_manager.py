# user_manager.py —— 用户管理：注册/登录/登出，bcrypt 加密存密码

# 标准库 json：JSON 工具（本文件暂未直接使用，预留）
import json
# 标准库 time：时间工具（预留）
import time
# 标准库 typing：类型标注 List（≈ Java 泛型 List，仅提示用）
from typing import List
# 第三方库 mongoengine：MongoDB 的 ODM（connect 连接、NotUniqueError 异常等），≈ JPA/Hibernate
from mongoengine import *
# 标准库 threading：线程锁工具，保证用户缓存并发安全（≈ java.util.concurrent）
import threading
# 从 entity/user_entity.py 导入 User 用户实体（≈ @Entity 用户表）
from entity import User
# 第三方库 cachetools：TTLCache 带过期时间的本地缓存（≈ Caffeine）
from cachetools import TTLCache
# 第三方库 bcrypt：密码哈希加密库（加盐、不可逆，≈ BCryptPasswordEncoder）
import bcrypt
# 从 utils/__init__.py 取全局日志器和新用户默认权限常量
from utils import logger, DEFAULT_PERMISSIONS
# 标准库 traceback：异常堆栈打印（≈ e.printStackTrace()）
import traceback

# 密码加密函数：明文密码 → bcrypt 密文（加盐哈希不可逆，库里只存密文）
def hash_password(password: str) -> str:
    """对密码进行哈希加密"""
    # 底层实现，不用看：第三方库 bcrypt 生成随机盐（≈ BCryptPasswordEncoder.encode）
    salt = bcrypt.gensalt()
    # 用盐对明文做哈希；encode('utf-8') 是 str 转字节，bcrypt 只吃字节
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    # 把密文字节转回字符串返回，供存入 MongoDB
    return hashed.decode('utf-8')

# 密码校验函数：比对登录输入的明文密码和库里的密文是否匹配
def verify_password(password: str, hashed_password: str) -> bool:
    """验证密码是否正确"""
    # 底层实现，不用看：第三方库 bcrypt.checkpw 做密文比对（≈ BCryptPasswordEncoder.matches）
    return bcrypt.checkpw(
        password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )

# 用户管理类：封装注册/登录/登出/在线判断（≈ @Service 的 UserService）
class UserManagerHub:
    # 构造方法：保存连接参数、建 MongoDB 连接、创建用户缓存和锁
    def __init__(self, mongo_host, mongo_db, mongo_port):
        # 保存 MongoDB 地址（self.xxx ≈ this.xxx）
        self.mongo_host = mongo_host
        # 保存数据库名
        self.mongo_db = mongo_db
        # 保存端口
        self.mongo_port = mongo_port
        # 调用 mongoengine 的 connect() 建立 MongoDB 连接
        self.mongoClient = connect(mongo_db, host=mongo_host, port=mongo_port)
        # 保存数据库名称
        self.db_name = mongo_db
        # 创建互斥锁，保护 user_cache 并发读写（≈ ReentrantLock）
        self.cache_lock = threading.Lock()
        # 创建在线用户缓存：最多 100 个、1 小时过期（≈ Caffeine）
        self.user_cache = TTLCache(maxsize=100, ttl=3600)

    # 确保 MongoDB 连接有效：连接断了就自动重连
    def _ensure_connection(self):
        """确保MongoDB连接有效，如果连接已关闭则重新连接"""
        # try：先探活检查连接
        try:
            # 发 ping 命令检测连接是否有效（≈ 数据库心跳检测）
            self.mongoClient.admin.command('ping')
        # except：连接已失效时走重连（≈ catch）
        except Exception:
            # try：重建连接
            try:
                # 调用 mongoengine 的 connect() 重新连 MongoDB
                self.mongoClient = connect(self.mongo_db, host=self.mongo_host, port=self.mongo_port)
            # except：重连也失败就记日志再抛出
            except Exception as e:
                # 记录错误日志（f"" ≈ String.format）
                logger.error(f"重新连接MongoDB失败: {e}")
                # raise 重新抛出异常交给上层处理（≈ throw e）
                raise

    # 生成下一个用户 ID：用 MongoDB 原子自增（counters 集合模拟数据库 sequence）
    def get_next_user_id(self):
        # 先确保连接有效
        self._ensure_connection()
        # 按名字取数据库对象（≈ getDatabase(dbName)）
        db = self.mongoClient[self.db_name]
        # 调 findOneAndUpdate 原子自增 counters 的 sequence_value（$inc 自增天然并发安全）
        counter = db.counters.find_one_and_update(
            {"_id": "user_id"},
            {"$inc": {"sequence_value": 1}},
            upsert=True,
            return_document=True
        )
        # 返回自增后的值作为新用户 ID
        return counter["sequence_value"]

    # 注册新用户：查重 -> 分配 ID -> 密码加密 -> 存 MongoDB，返回 (状态码, 提示信息)
    def create_user(self, user_name, password, confirm_password, permissions=None):
        # 判断两次输入的密码是否一致
        if password != confirm_password:
            # 不一致直接拒绝，返回 400
            return 400, "两次输入的密码不一致"

        # try：入库过程可能抛异常
        try:
            # 调用 entity/user_entity.py 的 User 实体按用户名查重（.first() 没有则返回 None ≈ null）
            if User.objects(userName=user_name).first():
                # 已存在同名用户，返回 409
                return 409, "该用户已注册"

            # 调本类 get_next_user_id() 原子获取用户 ID
            user_id = self.get_next_user_id()
            # 调本类 hash_password() 给密码加密后再入库（绝不存明文）
            password = hash_password(password)
            # 判断是否传了权限参数
            if permissions is None:
                # 没传就用 utils/const.py 的 DEFAULT_PERMISSIONS 默认权限（≈ getOrDefault）
                permissions = DEFAULT_PERMISSIONS
            # 调用 entity/user_entity.py 的 User 实体组装用户（≈ @Builder 构造实体）
            current_user = User(user_id=user_id, userName=user_name, password=password, user_authority=permissions)
            # 保存进 MongoDB（≈ JPA save）
            current_user.save()
            # 返回 200 注册成功
            return 200, "用户注册成功"
        # except：用户名唯一索引冲突（≈ DataIntegrityViolationException）
        except NotUniqueError:
            # 返回 409 用户已存在
            return 409, "用户已存在"
        # except：其他异常兜底
        except Exception as e:
            # 记录错误日志（含异常堆栈）
            logger.error(f"注册失败: {e}\n{traceback.format_exc()}")
            # 返回 500 和错误信息
            return 500, f"注册失败: {str(e)}"

    # 登录：校验用户名密码，成功则放进在线缓存，失败返回 user_id=-1 的占位对象
    def login(self, user_name, password):
        # try：查询/校验可能抛异常
        try:
            # 调用 entity/user_entity.py 的 User 实体按用户名查询
            users = User.objects(userName=user_name)
            # 判断是否查到记录（非空 ≈ != null）
            if users:
                # 取第一条记录
                user = users.first()
                # 取出库里存的密码密文
                stored_password = user.password
                # 判断密文是否字符串类型（isinstance ≈ instanceof）
                if isinstance(stored_password, str):
                    # str 转字节数组，bcrypt 校验需要字节
                    stored_password = stored_password.encode('utf-8')
                # 底层实现，不用看：第三方库 bcrypt.checkpw 比对明文和密文（≈ BCrypt matches）
                if bcrypt.checkpw(password.encode('utf-8'), stored_password):
                    # with 加锁写缓存，退出自动释放
                    with self.cache_lock:
                        # 把用户存进在线缓存（dict 赋值 ≈ map.put）
                        self.user_cache[user.user_id] = user
                    # 返回用户对象表示登录成功
                    return user
        # except：登录异常兜底
        except Exception as e:
            # 记录错误日志（含异常堆栈）
            logger.error(f"登录失败: {e}\n{traceback.format_exc()}")
        # 用户不存在或密码错误：返回 user_id=-1 占位对象表示失败
        return User(user_id=-1)

    # 登出：把用户从在线缓存中移除
    def logout(self, user_id):
        # with 加锁，保证并发安全
        with self.cache_lock:
            # 从缓存删除该用户；None 表示 key 不存在也不报错（≈ map.remove(k)）
            self.user_cache.pop(user_id, None)
        # 固定返回 True 表示登出成功
        return True

    # 判断用户是否在线（是否在缓存中）
    def islogin(self,user_id):
        # 从缓存取用户（≈ map.get(k)）
        user = self.user_cache.get(user_id)
        # 判断是否取到（None ≈ null）
        if user is None:
            # 没取到返回 False
            return False
        # 取到走 else
        else:
            # 返回 True 表示在线
            return True


# 直接运行本文件时走这里的本地测试入口（≈ Java main 方法）
if __name__ == "__main__":
    # 创建用户管理器，连本机 MongoDB
    userManagerHub = UserManagerHub('localhost', "tools", 27017)
    # 测试登录：用账号 zxyk 登录
    user1 = userManagerHub.login("zxyk","123456")
    # 打印登录后是否在线（应输出 True）
    logger.info(userManagerHub.islogin(user1.user_id))
    # 测试登出
    userManagerHub.logout(user1.user_id)
    # 打印登出后是否在线（应输出 False）
    logger.info(userManagerHub.islogin(user1.user_id))
