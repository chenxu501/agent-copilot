# train_embedding.py —— 【不用学，进阶可选，默认用不到】用句子对数据微调训练中文向量模型的脚本

# 导入 json，用来读训练数据文件
import json

# 导入句向量模型、样本、损失函数、评估器（训练组件，不用细看）
from sentence_transformers import SentenceTransformer, InputExample, losses, evaluation
# 导入 PyTorch 的数据加载器，训练时分批喂数据（≈ 分批的 Iterator）
from torch.utils.data import DataLoader
# 导入 pandas（原代码保留，实际没用到）
import pandas as pd




# 训练主流程：读数据 -> 加载底座模型 -> 训练 -> 保存
def train(train_file):
    # 假设你有一个包含句子对的 CSV 文件，其中第一列为句子1，第二列为句子2，第三列为相似度标签（0或1）
    with open(train_file,encoding='utf-8')as f:
        # 把 json 训练数据读成列表
        datas = json.load(f)
        # 建个空列表装训练样本
        train_examples = []
        # 遍历每条数据，造一正一负两个样本
        for data in datas:
            # 正样本：意思相近的句子对，标签 1
            train_examples.append(InputExample(texts=[data["sentences"], data["api"]], label=1))
            # 负样本：意思不相近的句子对，标签 0
            train_examples.append(InputExample(texts=[data["negative_sentences"], data["api"]], label=0))


    # 加载预训练的中文向量模型当训练底座
    model = SentenceTransformer("/root/autodl-tmp/models/BAAI/bge-large-zh-v1.5")

    # 定义训练用的损失函数（底层组件，不用看）
    train_loss = losses.CosineSimilarityLoss(model=model)
    # 定义数据加载器：打乱顺序、每批 16 条
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=16)
    # 训练轮数设为 3
    num_epochs = 3

    # 定义评估器：拿前 100 条样本当验证集，训练中顺便评估效果
    evaluator = evaluation.EmbeddingSimilarityEvaluator.from_input_examples(
        train_examples[:100], name="validation"
    )

    # 开始训练（参数是训练组件配置，不用看）
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=num_epochs,
        evaluator=evaluator,
        evaluation_steps=1000,
        save_best_model=True,
        show_progress_bar=True,
    )

    # 把训练好的模型保存到 output/bge_model 目录
    model.save("output/bge_model")


# 直接运行本文件才开始训练（≈ main 方法）
if __name__ == "__main__":
    # 用训练数据文件跑一次训练
    train("new_dataset_train.json")
