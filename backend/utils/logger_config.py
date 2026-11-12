# logger_config.py —— 日志配置：全局 logger 同时输出到控制台和 logs/copilot.log（按天滚动）

# 标准库 logging：Python 标准日志库（≈ SLF4J + Logback）
import logging
# 标准库 os：文件/目录操作，创建 logs 目录用（≈ java.io.File）
import os
# 标准库 logging.handlers：按时间滚动的日志文件处理器（≈ Logback 按天滚动策略）
from logging.handlers import TimedRotatingFileHandler

# 配置并返回一个全局可用的 logger 实例
def setup_logger(logger_name='copilot'):
    """配置并返回一个全局可用的logger实例"""

    # 创建 logger；同名 getLogger 返回同一个对象（≈ LoggerFactory.getLogger）
    logger = logging.getLogger(logger_name)

    # 判断是否已挂过 handler（幂等保护，重复调用直接返回）
    if logger.handlers:
        # 已初始化过就返回现有 logger
        return logger

    # 设置日志级别为 DEBUG（debug/info/warning/error 全记录）
    logger.setLevel(logging.DEBUG)

    # 日志目录名 logs
    log_dir = 'logs'
    # 判断 logs 目录是否存在
    if not os.path.exists(log_dir):
        # 不存在就创建（≈ File.mkdirs()）
        os.makedirs(log_dir)

    # 底层实现，不用看：创建控制台输出 handler（≈ ConsoleAppender）
    console_handler = logging.StreamHandler()
    # 控制台 handler 也开 DEBUG 级别
    console_handler.setLevel(logging.DEBUG)
    # 底层实现，不用看：定义日志格式：时间-日志器名-级别-文件名:函数名:行号-消息（≈ Logback pattern）
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s'
    )
    # 把格式绑定到控制台 handler
    console_handler.setFormatter(console_formatter)
    # 把控制台 handler 挂到 logger 上
    logger.addHandler(console_handler)

    # 拼日志文件名 copilot.log（f"" ≈ String.format）
    log_file_name = f"{logger_name}.log"

    # 底层实现，不用看：创建按天滚动的文件 handler——午夜切新文件、只留最近 7 天，旧的自动删（≈ RollingFileAppender）
    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, log_file_name),
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    # 文件 handler 也开 DEBUG 级别
    file_handler.setLevel(logging.DEBUG)
    # 底层实现，不用看：文件日志用同样的格式模板
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s'
    )
    # 把格式绑定到文件 handler
    file_handler.setFormatter(file_formatter)
    # 把文件 handler 挂到 logger 上
    logger.addHandler(file_handler)

    # 返回配置好的 logger
    return logger

# 创建全局 logger 实例（模块被 import 时初始化一次，其他文件直接用）
logger = setup_logger()
