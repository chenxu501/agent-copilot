# mongdb_use.py —— 【不用学，学习示例，不参与运行】MongoDB 增删改查入门示例

# 导入 os 操作系统接口（本文件没直接用到，保留）
import os
# 导入 mongoengine 连接管理：连/断/取连接（≈ JDBC 的 DriverManager）
from mongoengine import connect, disconnect, get_connection
# 导入用户实体类（≈ @Entity 的 User）
from entity.user_entity import User
# 导入工具、参数实体类（示例里只用来清测试数据）
from entity.tool_entity import Tool, Parameter

# MongoDB 所在机器 IP，127.0.0.1 表示本机
MONGO_HOST = "127.0.0.1"
# 要用的库名（≈ MySQL 的 database）
MONGO_DB = "test"
# MongoDB 默认端口号（≈ MySQL 的 3306）
MONGO_PORT = 27017

# 连接 MongoDB，先断旧连接再重连（≈ DriverManager.getConnection）
def connect_mongodb():
    """连接到MongoDB数据库"""
    # 开始连接，出错接住不崩（try/except ≈ try/catch）
    try:
        # 取当前已建立的连接
        existing_connection = get_connection()
        # 判断旧连接存不存在
        if existing_connection:
            # 断开旧连接（≈ close()）
            disconnect()
    # 捕获检查连接时的异常
    except Exception as e:
        # 打印提示后继续重建连接
        print(f"检查已有MongoDB连接时出错: {e}，将重新建立连接。")

    # 建立新的 MongoDB 连接
    client = connect(MONGO_DB, host=MONGO_HOST, port=MONGO_PORT)
    # 打印连接成功
    print(f"成功连接到MongoDB: {MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}")
    # 返回连接对象（≈ Connection）
    return client

# 增操作：新建用户存进 MongoDB（≈ em.persist()）
def create_user(user_id, username, password):
    """创建用户 - 增加操作"""
    # 开始创建，出错接住返回 None
    try:
        # 在内存里 new 一个用户对象
        user = User(
            user_id=user_id,
            userName=username,
            password=password
        )
        # 保存到 MongoDB，插入一条
        user.save()
        # 打印成功
        print(f"成功创建用户: {username}")
        # 返回新建的用户
        return user
    # 捕获创建失败的异常
    except Exception as e:
        # 打印失败原因
        print(f"创建用户失败: {e}")
        # 返回 None（≈ null）
        return None

# 查操作：按用户名精确查（≈ selectOne）
def get_user(username):
    """获取用户信息 - 查询操作"""
    # 开始查询，出错接住返回 None
    try:
        # 按用户名查，.first() 只取第一条
        user = User.objects(userName=username).first()
        # 判断查没查到（对象非 None 即真）
        if user:
            # 打印查到的用户
            print(f"找到用户: {user.userName}, ID: {user.user_id}")
            # 返回用户对象
            return user
        else:
            # 打印没找到
            print(f"未找到用户: {username}")
            # 返回 None
            return None
    # 捕获查询失败的异常
    except Exception as e:
        # 打印失败原因
        print(f"查询用户失败: {e}")
        # 返回 None
        return None

# 改操作：先查再改密码再保存（≈ merge 更新）
def update_user(username, new_password):
    """更新用户信息 - 修改操作"""
    # 开始更新，出错接住返回 None
    try:
        # 先查出这条数据
        user = User.objects(userName=username).first()
        # 判断查没查到
        if user:
            # 改内存对象的密码（≈ setter）
            user.password = new_password
            # 重新保存即更新这条数据
            user.save()
            # 打印成功
            print(f"成功更新用户密码: {username}")
            # 返回更新后的用户
            return user
        else:
            # 打印没找到
            print(f"未找到用户: {username}")
            # 返回 None
            return None
    # 捕获更新失败的异常
    except Exception as e:
        # 打印失败原因
        print(f"更新用户失败: {e}")
        # 返回 None
        return None

# 删操作：查出来再删（≈ em.remove()）
def delete_user(username):
    """删除用户 - 删除操作"""
    # 开始删除，出错接住返回 False
    try:
        # 先查出要删的数据
        user = User.objects(userName=username).first()
        # 判断查没查到
        if user:
            # 删除这条数据
            user.delete()
            # 打印成功
            print(f"成功删除用户: {username}")
            # 返回 True 表示删掉了
            return True
        else:
            # 打印没找到
            print(f"未找到用户: {username}")
            # 返回 False 表示没删成
            return False
    # 捕获删除失败的异常
    except Exception as e:
        # 打印失败原因
        print(f"删除用户失败: {e}")
        # 返回 False
        return False

# 查所有用户（≈ select * from user）
def list_all_users():
    """列出所有用户"""
    # 开始查询，出错接住返回空列表
    try:
        # 不加条件查全表
        users = User.objects()
        # 打印总条数
        print(f"共找到 {users.count()} 个用户:")
        # 遍历每条（≈ 增强 for）
        for user in users:
            # 打印这条的 id 和用户名
            print(f"  - ID: {user.user_id}, Username: {user.userName}")
        # 结果集合转列表返回（≈ List<User>）
        return list(users)
    # 捕获查询失败的异常
    except Exception as e:
        # 打印失败原因
        print(f"查询用户列表失败: {e}")
        # 返回空列表（≈ Collections.emptyList()）
        return []

# 主函数：按顺序演示一遍增删改查
def main():
    """主函数，演示MongoDB的基本操作"""
    # 打印标题
    print("MongoDB基本操作示例")
    # 打印 30 个 = 号当分隔线
    print("=" * 30)

    # 连接到 MongoDB
    client = connect_mongodb()

    # 清掉上次残留的测试用户
    User.objects(userName="test_user").delete()
    # 清掉另一个测试用户
    User.objects(userName="updated_user").delete()
    # 清掉测试工具数据
    Tool.objects(operationId="test_operation").delete()

    # 打印用户操作标题
    print("\n--- 用户操作示例 ---")

    # 打印步骤 1 标题
    print("\n1. 创建用户:")
    # 调创建用户（增）
    user1 = create_user(1001, "test_user", "password123")

    # 打印步骤 2 标题
    print("\n2. 查询用户:")
    # 调查询用户（查）
    user_found = get_user("test_user")

    # 打印步骤 3 标题
    print("\n3. 更新用户:")
    # 调更新密码（改）
    update_user("test_user", "newpassword456")

    # 打印步骤 4 标题
    print("\n4. 验证更新:")
    # 再查一次看密码改没改
    get_user("test_user")

    # 再建一个用户，方便后面列表展示
    create_user(1002, "updated_user", "anotherpass")

    # 打印步骤 5 标题
    print("\n5. 列出所有用户:")
    # 调列出所有用户
    list_all_users()

    # 打印步骤 6 标题
    print("\n6. 删除用户:")
    # 调删除用户（删）
    delete_user("test_user")

    # 打印步骤 7 标题
    print("\n7. 验证删除:")
    # 预期打印"未找到用户"，说明删成功了
    get_user("test_user")

    # 打印结束
    print("\n--- 示例结束 ---")

# 直接运行本文件才执行 main（≈ main 方法）
if __name__ == "__main__":
    # 跑演示
    main()
