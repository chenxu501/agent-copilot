# function_util.py —— 杂项工具函数：目前只有函数执行计时装饰器 timing_decorator

# 标准库 logging：用 logging.debug 输出计时结果（≈ SLF4J Logger）
import logging
# 标准库 time：perf_counter() 高精度计时器（≈ System.nanoTime()）
import time

# 函数执行计时装饰器：在被装饰函数执行前后记录时间差（≈ @Around 环绕通知）
def timing_decorator(func):
    # 包装函数：接收任意参数并透传给原函数（*args/**kwargs ≈ 可变参数 Object...）
    def wrapper(*args, **kwargs):
        # 记录开始时间（高精度计时）
        start_time = time.perf_counter()
        # 执行原函数（≈ 反射调用 method.invoke()）
        result = func(*args, **kwargs)
        # 记录结束时间
        end_time = time.perf_counter()
        # 打印耗时到 debug 日志（:.6f 保留 6 位小数）
        logging.debug(f"Function {func.__name__} execution time: {end_time - start_time:.6f} seconds")
        # 把原函数的返回值原样返回（不能吞掉）
        return result

    # 返回包装后的新函数
    return wrapper
