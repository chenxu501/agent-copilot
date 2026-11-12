# local_reranker_model.py —— 【不用学】本地 BGE 重排序模型封装：给检索结果重新打分排序
"""
BGE重排序模型实现
使用modelscope上的BAAI/bge-reranker-v2-m3模型
"""

# 导入 PyTorch，模型推理用（底层实现，不用看）
import torch
# 导入 os，读环境变量里的模型令牌（os.getenv ≈ System.getenv）
import os

# 导入自定义日志工具（≈ slf4j 的 Logger）
from utils import logger


# BGE 重排序模型封装类：对候选文本按相关度打分排序
class BGEReranker:
    # 构造方法：加载分词器和打分模型（≈ 初始化本地引擎）
    def __init__(self, model_name="BAAI/bge-reranker-v2-m3", use_fp16=True, use_modelscope=True):
        """
        初始化BGE重排序模型

        Args:
            model_name (str): 模型名称，默认为"BAAI/bge-reranker-v2-m3"
            use_fp16 (bool): 是否使用半精度浮点数
            use_modelscope (bool): 是否使用ModelScope而不是Hugging Face
        """
        # 记住模型名
        self.model_name = model_name
        # 记住是否用半精度
        self.use_fp16 = use_fp16

        # 初始化日志对象
        self.logger = logger.getLogger(__name__)

        # 开始加载模型，出错接住后抛出（try/except ≈ try/catch）
        try:
            # 判断走 ModelScope 还是 Hugging Face 加载
            if use_modelscope:
                # 从 ModelScope 导入加载器（底层实现，不用看）
                from modelscope import AutoModelForSequenceClassification, AutoTokenizer
                # 加载分词器，文本转 token
                self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                # 加载序列打分模型
                self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            else:
                # 从 Hugging Face 导入加载器（底层实现，不用看）
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                # 读环境变量里的访问令牌
                token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")

                # 判断有没有令牌
                if token:
                    # 有令牌就带令牌加载分词器
                    self.tokenizer = AutoTokenizer.from_pretrained(model_name, token=token)
                    # 带令牌加载模型
                    self.model = AutoModelForSequenceClassification.from_pretrained(model_name, token=token)
                else:
                    # 没令牌就直接加载分词器
                    self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                    # 直接加载模型
                    self.model = AutoModelForSequenceClassification.from_pretrained(model_name)

            # 选设备：有显卡用 cuda，否则用 cpu
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            # 把模型放到对应设备
            self.model = self.model.to(self.device)

            # 判断能不能用半精度
            if use_fp16 and torch.cuda.is_available():
                # 转半精度，更省显存更快
                self.model = self.model.half()

            # 切到评估模式，推理更稳
            self.model.eval()

            # 打日志报告加载成功
            self.logger.info(f"BGE重排序模型加载成功，使用设备: {self.device}")

        # 捕获加载失败的异常
        except Exception as e:
            # 记录失败日志
            self.logger.error(f"加载BGE重排序模型失败: {e}")
            # 把异常抛出去（≈ throw）
            raise e

    # 对候选结果重排序，返回下标（或下标+分数）
    def rerank(self, query, candidates, return_scores=False):
        """
        对候选结果进行重排序

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

        # 开始打分排序，出错兜底返回原顺序
        try:
            # 把查询和每个候选两两配对交给模型打分
            pairs = [[query, candidate] for candidate in candidates]

            # 只推理不记梯度（with ≈ try-with-resources）
            with torch.no_grad():
                # 分词后搬到设备（底层实现，不用看：tokenizer 参数）
                inputs = self.tokenizer(
                    pairs,
                    padding=True,
                    truncation=True,
                    return_tensors='pt',
                    max_length=512
                ).to(self.device)

                # 模型推理，得到每个对的原始分
                scores = self.model(**inputs, return_dict=True).logits.view(-1, ).float()
                # 用 sigmoid 把分数压到 0~1 当相关度
                scores = torch.sigmoid(scores)

                # 分数搬到 CPU 转 numpy 数组
                scores_cpu = scores.cpu().numpy()

                # 按分数降序取下标（分越高越靠前）
                sorted_indices = scores_cpu.argsort()[::-1]

                # 判断要不要连分数一起返回
                if return_scores:
                    # 返回下标列表和分数列表
                    return sorted_indices.tolist(), scores_cpu.tolist()
                else:
                    # 只返回下标列表
                    return sorted_indices.tolist()

        # 捕获排序过程中的异常
        except Exception as e:
            # 记录错误日志
            self.logger.error(f"重排序过程中发生错误: {e}")
            # 兜底：失败就返回原始顺序
            original_indices = list(range(len(candidates)))
            # 判断要不要连分数一起返回
            if return_scores:
                # 返回原顺序和全 0 分数
                return original_indices, [0.0] * len(candidates)
            else:
                # 只返回原顺序
                return original_indices

    # 重排序并返回带文本和分数的详细结果
    def rerank_with_details(self, query, candidates):
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
        # 按排序后的顺序逐个组装
        for idx in sorted_indices:
            # 拼一条"下标+文本+分数"的记录（dict ≈ Map）
            reranked_results.append({
                'index': idx,
                'text': candidates[idx],
                'score': scores[idx]
            })

        # 返回详细结果
        return reranked_results

# 单例缓存变量，保证全局只加载一次模型（≈ 单例 Bean 字段）
_reranker_instance = None

# 获取重排序模型的单例（≈ 单例工厂方法）
def get_reranker_instance(use_modelscope=True):
    """
    获取重排序模型单例实例

    Args:
        use_modelscope (bool): 是否使用ModelScope而不是Hugging Face
    """
    # 声明用模块级变量（不是局部变量）
    global _reranker_instance
    # 判断是不是第一次创建
    if _reranker_instance is None:
        # 第一次才真正加载模型
        _reranker_instance = BGEReranker(use_modelscope=use_modelscope)
    # 返回单例
    return _reranker_instance
