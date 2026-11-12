# embedding_model.py —— 【不用学】把文本转成向量的封装（本地模型版），当工具类调用即可

# 导入类型标注用的泛型标记，仅标注不影响运行（≈ List/Map/Set）
from typing import List, Mapping, Set

# 导入 numpy，算余弦相似度用（≈ 向量运算工具类）
import numpy as np
# 导入 requests 发 HTTP 请求（本文件没直接用到，保留）
import requests
# 导入计时装饰器，自动统计方法耗时（≈ AOP 环绕通知）
from utils.function_util import timing_decorator
# 导入 transformers 的分词器和模型加载器（底层实现，不用看）
from transformers import AutoTokenizer, AutoModel
# 导入 PyTorch，做模型推理用（底层实现，不用看）
import torch
# 导入按批次喂数据的加载器和张量数据集（底层实现，不用看）
from torch.utils.data import DataLoader, TensorDataset
# 导入进度条工具，长循环显示进度
from tqdm import tqdm
# 导入 JSON 处理（本文件没直接用到，保留）
import json
# 原代码重复导入 tqdm，保持原样
from tqdm import tqdm
# 导入 math，用向上取整算批次数
import math
# 导入句子转向量的库，算相似度用（≈ 工具类）
from sentence_transformers import SentenceTransformer


# 列表切分生成器：按固定大小一段段产出，防内存爆掉（≈ Iterator 分批）
def list_split(lst, chunk_size=10):
    # 一直切到列表切完为止
    while True:
        # 判断剩下的是不是超过一整段
        if len(lst) > chunk_size:
            # 产出前 chunk_size 个（yield ≈ 迭代器产出）
            yield lst[:chunk_size]
            # 去掉已产出的部分，继续切
            lst = lst[chunk_size:]
        else:
            # 最后不足一段，直接产出
            yield lst
            # 切完了，结束生成器
            break



# 本地向量模型封装类（里程碑3）：加载本地模型把文本转向量、算相似度
class EmbeddingModel:
    # 构造方法：加载分词器、向量模型和相似度模型（≈ 初始化引擎）
    def __init__(self, model_path):
        # 保存模型路径
        self.model_path = model_path
        # 指定跑在 CPU 上
        self.device = torch.device('cpu')
        # 加载分词器，文本转 token（底层实现，不用看）
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        # 加载模型本体，token 转向量（底层实现，不用看）
        self.embedding_model = AutoModel.from_pretrained(model_path)
        # 切到评估模式，关掉训练用的随机层
        self.embedding_model.eval()
        # 把模型放到指定设备
        self.embedding_model.to(self.device)
        # 再加载一个专门算句子向量/相似度的模型
        self.similarity_model = SentenceTransformer(model_path)
        # 放到指定设备
        self.similarity_model.to(self.device)
        # 备用的 HTTP 请求头（本文件没用到，保留）
        self.headers = {'Content-Type': 'application/json'}

    # 挂计时装饰器，统计本方法耗时
    @timing_decorator
    # 批量把文本列表转成向量列表
    def get_batch_embeddings(self, texts, batch_size=128):
        # 存所有向量结果（≈ ArrayList）
        all_embeddings = []
        # 小份计数，只用于进度条显示
        chunk_id = 0
        # 算出一共切几小份（ceil 向上取整）
        total_chunks = math.ceil(len(texts) / 10)
        # 按每份 10 条切开逐份处理
        for content in list_split(texts, 10):
            # 份号加一
            chunk_id += 1
            # 分词：文本转 token，做补齐和截断（底层实现，不用看）
            encoded_input = self.tokenizer(content, padding=True, truncation=True, return_tensors='pt')
            # 判断这批数据带不带句对标记
            if 'token_type_ids' in encoded_input:
                # 带句对标记就打包三项数据
                dataset = TensorDataset(encoded_input['input_ids'], encoded_input['attention_mask'],
                                        encoded_input['token_type_ids'])
            else:
                # 不带就只打包两项
                dataset = TensorDataset(encoded_input['input_ids'], encoded_input['attention_mask'])
            # 按 batch_size 分批喂数据
            dataloader = DataLoader(dataset, batch_size=batch_size)
            # 存这一小份的向量
            lst_embeddings = []
            # 只推理不记梯度，省内存（with ≈ try-with-resources）
            with torch.no_grad():
                # 逐批推理，tqdm 显示进度
                for batch in tqdm(dataloader, desc=f'chunk {chunk_id:02d}/{total_chunks}'):
                    # 把这批数据搬到指定设备
                    batch = tuple(t.to(self.device) for t in batch)
                    # 组装模型输入
                    inputs = {'input_ids': batch[0], 'attention_mask': batch[1]}
                    # 判断有没有句对标记
                    if 'token_type_ids' in encoded_input:
                        # 补上句对标记
                        inputs['token_type_ids'] = batch[2]

                    # 喂给模型算输出（**inputs ≈ 按参数名传参）
                    model_output = self.embedding_model(**inputs)
                    # 取 [CLS] 位置输出当整句向量（[CLS] pooling）
                    embeddings = model_output[0][:, 0]
                    # L2 归一化，让向量长度为 1，方便算余弦相似度
                    embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
                    # 收进本小份结果
                    lst_embeddings.append(embeddings)

            # 把各批向量拼成一个大张量
            lst_embeddings = torch.cat(lst_embeddings, dim=0)
            # 搬回 CPU 并收进总结果
            all_embeddings.extend(lst_embeddings.cpu())

        # 返回全部向量
        return all_embeddings

    # 挂计时装饰器，统计本方法耗时
    @timing_decorator
    # 单条文本转成向量
    def get_embedding(self, text):
        # 分词：文本转 token（底层实现，不用看）
        encoded_input = self.tokenizer(text, padding=True, truncation=True, return_tensors='pt')

        # 取出 token id 序列搬到设备
        input_ids = encoded_input['input_ids'].to(self.device)
        # 取出注意力掩码搬到设备
        attention_mask = encoded_input['attention_mask'].to(self.device)

        # 判断带不带句对标记
        if 'token_type_ids' in encoded_input:
            # 带就取出来搬到设备
            token_type_ids = encoded_input['token_type_ids'].to(self.device)
        else:
            # 不带就置 None（≈ null）
            token_type_ids = None

        # 只推理不记梯度（with ≈ try-with-resources）
        with torch.no_grad():
            # 组装模型输入
            inputs = {'input_ids': input_ids, 'attention_mask': attention_mask}
            # 判断有没有句对标记
            if token_type_ids is not None:
                # 补上句对标记
                inputs['token_type_ids'] = token_type_ids

            # 喂给模型算输出
            model_output = self.embedding_model(**inputs)
            # 取 [CLS] 位置输出当句子向量
            embedding = model_output[0][:, 0]
            # L2 归一化
            embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

        # 搬回 CPU 返回
        return embedding.cpu()

    # 挂计时装饰器，统计本方法耗时
    @timing_decorator
    # 算查询句与候选句的相似度，按高到低返回
    def get_similarity(self, sentences: List[str], source_sentence: str, recall_num: int = -1,
                       threshold: float = 0):
        # 候选句批量转向量
        text_embeddings = self.similarity_model.encode(sentences)
        # 查询句转向量
        query_embedding = self.similarity_model.encode(source_sentence)

        # 算余弦相似度：两向量夹角余弦，越接近 1 越像
        cosine_similarities = np.dot(text_embeddings, query_embedding.T) / (
                np.linalg.norm(text_embeddings, axis=1) * np.linalg.norm(query_embedding))
        # 按相似度降序取下标（[::-1] 反转成从大到小）
        sorted_indices = cosine_similarities.argsort()[::-1]

        # 存筛选后的结果
        result_docs = []
        # 按相似度从高到低遍历
        for i in sorted_indices:
            # 判断是否超过阈值
            if cosine_similarities[i] > threshold:
                # 收进结果（按原代码保留：追加的是 sentences 整个列表）
                result_docs.append(sentences)
        # 判断要不要限制返回条数
        if recall_num == -1:
            # -1 表示不限量，全返回
            return result_docs
        # 判断结果超没超过要的条数
        if len(result_docs) > recall_num:
            # 超了就截取前 recall_num 条
            return result_docs[0:recall_num]
        else:
            # 没超就原样返回
            return result_docs
