# remote_embedding_model.py —— 【不用学】把文本转成向量的封装（远程接口版），当工具类调用即可

# 导入 numpy，算余弦相似度用（≈ 向量运算工具类）
import numpy as np
# 导入 OpenAI 客户端 SDK，调远程向量接口用（≈ HttpClient 封装）
from openai import OpenAI

# 从配置读大模型密钥和接口地址（≈ 读 application.yml 配置项）
from utils import model_api_key, model_base_url


# 远程转向量封装类：把文本发给远程接口换回向量
class RemoteEmbeddingModel:
    """
    初始化 RemoteEmbeddingModel 类的实例。
    此方法会创建一个 OpenAI 客户端实例，用于后续的嵌入向量生成操作。

    Attributes:
        openai_client (OpenAI): OpenAI 客户端实例，用于与 OpenAI API 进行交互。
                                配置了 API 密钥和基础 URL。
    """

    # 构造方法：创建可复用的远程接口客户端（≈ Java 构造函数）
    def __init__(self):
        # 用配置里的密钥和地址创建客户端
        self.openai_client = OpenAI(
            api_key=model_api_key,
            base_url=model_base_url
        )


    # 单条文本换向量
    def get_embedding(self, text):
        """
        根据输入的文本获取对应的嵌入向量。

        此函数会调用 OpenAI 客户端的嵌入向量生成接口，使用指定的模型 `text-embedding-3-large` 来生成文本的嵌入向量。

        参数:
            text (str): 用于生成嵌入向量的输入文本。

        返回:
            list: 生成的文本嵌入向量，以列表形式返回。

        代码流程逻辑:
            1. 调用 OpenAI 客户端的 `embeddings.create` 方法，传入模型名称和输入文本，获取响应。
            2. 从响应结果中提取第一个数据项的嵌入向量。
            3. 返回提取的嵌入向量。
        """
        # 调远程接口把文本换成向量
        response = self.openai_client.embeddings.create(model="text-embedding-v3", input=text)
        # 取第一个结果里的向量
        embeddings = response.data[0].embedding
        # 返回向量
        return embeddings


    # 批量文本换向量，分批调远程接口
    def get_batch_embeddings(self, texts, batch_size=10):
        """
        批量获取文本嵌入向量，支持超过10个文本的处理
        参数:
            texts (list): 输入文本列表
            batch_size (int): 每批处理的文本数量，默认为10
        返回:
            list: 文本嵌入向量列表
        """
        # 存所有向量结果（≈ ArrayList）
        all_embeddings = []

        # 每 batch_size 条一批循环处理
        for i in range(0, len(texts), batch_size):
            # 切出这一批的文本
            batch_texts = texts[i:i + batch_size]
            # 把这一批文本发远程接口换向量（底层实现，不用看：API 参数）
            response = self.openai_client.embeddings.create(
                model="text-embedding-v3",
                input=batch_texts
            )
            # 拿到这一批的返回结果
            embeddings = response.data
            # 逐条取出向量
            for tmp in embeddings:
                # 收进总结果
                all_embeddings.append(tmp.embedding)

        # 返回全部向量
        return all_embeddings



    # 算查询向量和候选文本的相似度，按高到低返回文本
    def get_similarity(self, target_texts, vectors, query, recall_num: int = 5, threshold: float = 0):
        """
        根据输入的查询向量和文本向量列表，计算查询向量与文本向量的余弦相似度。

        此函数会根据输入的查询向量和文本向量列表，使用余弦相似度来计算它们之间的相似程度。余弦相似度是一种常用的相似度度量方法，用于衡量两个向量之间的夹角余弦值。

        参数:
            target_texts (list): 文本向量列表，列表中的每个元素为一个文本向量。
            vectors (list): 文本向量列表，列表中的每个元素为一个文本向量。
            query (list): 查询向量，用于与文本向量进行比较。
            recall_num (int): 返回的相似文本数量，默认为 5。
            threshold (float): 相似度阈值，默认为 0。

        返回:
            list: 相似文本列表，列表中的每个元素为一个文本向量。

        代码流程逻辑:
            1. 将查询向量和文本向量列表转换为 numpy 数组。
            2. 计算查询向量的范数。
            3. 计算文本向量列表的范数。
            4. 计算余弦相似度。
            5. 按相似度降序排序。
            6. 返回相似文本列表。
        """
        # 查询向量转 numpy 数组，方便做向量运算
        query = np.array(query)
        # 候选向量也转 numpy 数组
        vectors = np.array(vectors)

        # 算查询向量的长度（模）
        norm_query = np.linalg.norm(query)
        # 算每个候选向量的长度（模）
        norm_vectors = np.linalg.norm(vectors, axis=1)
        # 算余弦相似度，越接近 1 越像
        cosine_similarities = np.dot(vectors, query) / (norm_vectors * norm_query)

        # 按相似度降序取下标（[::-1] 反转成从大到小）
        sorted_indices = cosine_similarities.argsort()[::-1]

        # 存筛选后的结果
        result_docs = []
        # 按相似度从高到低遍历
        for i in sorted_indices:
            # 判断是否超过阈值
            if cosine_similarities[i] > threshold:
                # 超过就保留对应文本
                result_docs.append(target_texts[i])
            # 判断够不够 recall_num 条
            if recall_num != -1 and len(result_docs) >= recall_num:
                # 够了就提前结束
                break

        # 返回命中的文本列表
        return result_docs


# 直接运行本文件才走下面的测试（≈ main 方法）
if __name__ == "__main__":
    # 创建远程转向量实例
    embeddingModel = RemoteEmbeddingModel()
    # 测试批量转向量
    x = embeddingModel.get_batch_embeddings(["你好！", "hello"])
    # 再建一个实例
    embeddingModel = RemoteEmbeddingModel()
    # 测试单条转向量
    y = embeddingModel.get_embedding("hello")
