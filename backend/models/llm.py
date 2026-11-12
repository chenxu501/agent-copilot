# llm.py —— 【了解即可】大模型调用封装：把提示词发给通义千问并拿回回答

# 导入时间模块，失败后等待重试用（time.sleep ≈ Thread.sleep）
import time
# 导入计时装饰器，自动统计方法耗时（装饰器 ≈ 注解 + AOP）
from utils.function_util import timing_decorator
# 导入随机数模块，生成随机等待秒数
import random
# 导入自定义日志工具，记录运行信息（≈ slf4j 的 Logger）
from utils import logger
# 导入堆栈打印工具，出错时留完整现场（≈ e.printStackTrace()）
import traceback
# 原代码重复导入时间模块，保持原样
import time
# 原代码重复导入计时装饰器，保持原样
from utils.function_util import timing_decorator
# 原代码重复导入随机数模块，保持原样
import random
# 导入 OpenAI 客户端 SDK，发大模型请求用（≈ HttpClient 封装）
from openai import OpenAI


# 定义大语言模型调用封装类
class LargeLanguageModel:
    # 构造方法：创建客户端并设重试次数（≈ Java 构造函数）
    def __init__(self, api_url, api_key):
        # 创建 OpenAI 客户端，配好密钥和接口地址
        self.openai_client = OpenAI(
            api_key=api_key,
            base_url=api_url
        )
        # 设置失败重试次数上限
        self.retries = 3

    # 带上下文的对话：拼上最近 N 条历史消息让模型续写
    def context_chat_completions(self, contexts, model, temperature, top_p, context_number):
        # 失败自动重试，最多试 retries 次
        for i in range(self.retries):
            # 开始一次调用尝试（try/except ≈ try/catch）
            try:
                # 建消息列表，先放一条系统消息设定助手角色
                messages = [
                    {"role": "system", "content": "You are a helpful assistant."}
                ]
                # 判断历史消息够不够指定条数
                if len(contexts) < context_number:
                    # 不够就全部带上
                    target_contexts = contexts
                else:
                    # 够就只切出末尾 context_number 条（≈ subList）
                    target_contexts = contexts[len(contexts) - context_number:len(contexts)]
                # 把历史消息追加进消息列表（≈ List.addAll）
                messages.extend(target_contexts)
                # 调大模型对话接口拿回复（底层实现，不用看：SDK 参数）
                response = self.openai_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p
                )
                # 取出回复文本
                message_content = response.choices[0].message.content
                # 返回回复文本
                return message_content
            # 捕获所有异常，接住后走重试（except ≈ catch）
            except Exception as err:
                # 记录错误日志，附完整堆栈
                logger.error(f"与模型'{model}' 交互时发生错误: {err}\n{traceback.format_exc()}")
                # 等一会儿再重试，避免打爆服务
                self.backoff()

    # 单轮对话：一段提示词换一段回答
    def chat_completions(self, prompt, model, temperature, top_p):
        # 失败自动重试，最多试 retries 次
        for i in range(self.retries):
            # 开始一次调用尝试
            try:
                # 调大模型对话接口，系统消息+用户提示词一起发（底层实现，不用看：SDK 参数）
                response = self.openai_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    top_p=top_p
                )
                # 取出回复文本并返回
                return response.choices[0].message.content
            # 捕获所有异常
            except Exception as err:
                # 记录错误日志
                logger.error(f"与模型'{model}' 交互时发生错误: {err}")
                # 判断是不是最后一次重试
                if i == self.retries - 1:
                    # 是最后一次就把异常抛出去（≈ throw）
                    raise
                # 还没到上限，等一会儿再试
                self.backoff()

    # 退避等待：重试前先睡一会儿
    def backoff(self, wait=None):
        # 判断有没有指定等待秒数
        if wait is None:
            # 没指定就随机等 1~20 秒
            time.sleep(random.randint(1, 20))
        else:
            # 指定了就按指定秒数等
            time.sleep(wait)


# 直接运行本文件才走下面的测试（≈ main 方法）
if __name__ == "__main__":

    # 测试用密钥，跑时自己填
    api_key = ""
    # 测试用接口地址，跑时自己填
    base_url = ""
    # 创建大模型封装实例
    llm = LargeLanguageModel(base_url, api_key)

    # 测试提示词
    test_prompt = "请介绍一下Python语言"
    # 测试模型名
    test_model = "deepseek-v3"
    # 测试温度参数
    test_temperature = 0.7
    # 测试核采样参数
    test_top_p = 1.0

    # 开始测试调用
    try:
        # 调单轮对话拿结果
        result = llm.chat_completions(test_prompt, test_model, test_temperature, test_top_p)
        # 打印标题
        logger.info("模型返回结果:")
        # 打印模型回复
        logger.info(result)
    # 测试出错时接住
    except Exception as e:
        # 打印错误信息
        logger.info(f"测试过程中发生错误: {e}")
