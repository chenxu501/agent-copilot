# qwen_reranker_model.py —— 【不用学】远程重排序封装（通义千问 API 版）：给检索结果重新打分排序
"""
通义千问gte-rerank-v2模型实现
通过API调用通义千问的重排序服务
"""

# 导入类型标注（List/Union ≈ 泛型，仅标注不影响运行）
from typing import List, Tuple, Union
# 导入通义千问官方 SDK，调重排序服务用（≈ 第三方 API 客户端）
import dashscope
# 导入 HTTP 状态码常量（HTTPStatus.OK ≈ HttpStatus.OK）
from http import HTTPStatus

# 导入自定义日志工具（≈ slf4j 的 Logger）
from utils import logger


# 通义千问重排序封装类：调远程接口给候选打分排序
class QwenReranker:
    # 构造方法：存密钥并配到 SDK 上（≈ Java 构造函数）
    def __init__(self, api_key: str):
        """
        初始化通义千问重排序模型
        Args:
            api_key (str): 通义千问API密钥
        """
        # 保存 API 密钥
        self.api_key = api_key
        # 把密钥配到 dashscope 全局配置，之后请求都带上
        dashscope.api_key = api_key

    # 用通义千问 gte-rerank-v2 给候选结果重排序
    def rerank(self, query: str, candidates: List[str], return_scores: bool = False) -> Union[List[int], Tuple[List[int], List[float]]]:
        """
        使用通义千问gte-rerank-v2模型对候选结果进行重排序
        Args:
            query (str): 查询文本
            candidates (list): 候选文本列表
            return_scores (bool): 是否返回分数
        Returns:
            list: 重排序后的候选结果索引列表，或(索引列表, 分数列表)元组
        """
        # 判断有没有候选
        if not candidates:
            # 没有就直接返回空
            return [] if not return_scores else ([], [])
        # 开始调接口，失败兜底返回原顺序
        try:
            # 调通义千问重排序接口，全部候选都参与打分（底层实现，不用看：API 参数）
            response = dashscope.TextReRank.call(
                model="gte-rerank-v2",
                query=query,
                documents=candidates,
                top_n=len(candidates),
                return_documents=True
            )
            # 判断接口调用成不成功
            if response.status_code == HTTPStatus.OK:
                # 取出打分结果
                results = response.output.results
                # 提取排序后的原始下标
                indices = [item["index"] for item in results]
                # 提取每个候选的相关度得分
                scores = [item["relevance_score"] for item in results]

                # 判断要不要连分数一起返回
                if return_scores:
                    # 返回下标列表和分数列表
                    return indices, scores
                else:
                    # 只返回下标列表
                    return indices
            else:
                # 记录接口调用失败的日志
                logger.error(f"通义千问重排序API调用失败，状态码: {response.status_code}, 错误信息: {response.message}")
                # 兜底：失败就返回原始顺序
                original_indices = list(range(len(candidates)))
                # 判断要不要连分数一起返回
                if return_scores:
                    # 返回原顺序和全 0 分数
                    return original_indices, [0.0] * len(candidates)
                else:
                    # 只返回原顺序
                    return original_indices

        # 捕获调用过程中的异常
        except Exception as e:
            # 记录错误日志
            logger.error(f"通义千问重排序过程中发生错误: {e}")
            # 兜底：返回原始顺序
            original_indices = list(range(len(candidates)))
            # 判断要不要连分数一起返回
            if return_scores:
                # 返回原顺序和全 0 分数
                return original_indices, [0.0] * len(candidates)
            else:
                # 只返回原顺序
                return original_indices

    # 重排序并返回带文本和分数的详细结果
    def rerank_with_details(self, query: str, candidates: List[str]) -> List[dict]:
        """
        对候选结果进行重排序并返回详细信息
        Args:
            query (str): 查询文本
            candidates (list): 候选文本列表

        Returns:
            list: 包含候选文本和对应分数的排序列表
        """
        # 调 rerank 拿排序下标和分数
        sorted_indices, scores = self.rerank(query, candidates, return_scores=True)
        # 存详细结果
        reranked_results = []
        # 按排序后的顺序逐个组装（第 i 名对应 scores[i]）
        for i, idx in enumerate(sorted_indices):
            # 拼一条"下标+文本+分数"的记录（dict ≈ Map）
            reranked_results.append({
                'index': idx,
                'text': candidates[idx],
                'score': scores[i]
            })

        # 返回详细结果
        return reranked_results

# 单例缓存变量，保证全局只创建一次（≈ 单例 Bean 字段）
_qwen_reranker_instance = None

# 获取通义千问重排序模型的单例（≈ 单例工厂方法）
def get_qwen_reranker_instance(api_key: str):
    """
    获取通义千问重排序模型单例实例
    Args:
        api_key (str): 通义千问API密钥
    """
    # 声明用模块级变量（不是局部变量）
    global _qwen_reranker_instance
    # 判断是不是第一次创建
    if _qwen_reranker_instance is None:
        # 第一次才真正创建
        _qwen_reranker_instance = QwenReranker(api_key=api_key)
    # 返回单例
    return _qwen_reranker_instance
