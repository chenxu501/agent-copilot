# AI Agent 任务编排平台

输入一句自然语言需求，由 LLM 自动完成 **任务拆解 → 工具选型 → 参数提取 → 接口调用 → 结果总结** 的全流程闭环，前端以流程图的形式实时展示每一步的执行情况。

后端 Flask，向量检索 Milvus，工具元数据 MongoDB，模型走阿里云百炼（OpenAI 兼容协议）。

---

## 核心设计：三步漏斗式工具选型

工具库变大以后，"把所有工具描述塞进 prompt 让 LLM 挑"会同时遇到两个问题：token 成本随工具数线性增长，且候选过多时选中率会明显下降。因此选型拆成三级：

| 层级 | 手段 | 作用 |
|---|---|---|
| 1. 粗筛 | Milvus 向量语义检索，按 `topK` 召回候选 | 把候选从全量压到 10 个量级，控制 token 成本 |
| 2. 精排 | `gte-rerank-v2` 对候选重排序 | 修正向量检索"语义相近但意图不同"的误召回 |
| 3. 裁决 | LLM 结合用户原始需求做最终选择 | 处理需要业务常识才能判断的场景 |

召回、精排、裁决各管一段，任意一级失效都不会让整条链路崩掉。

## 执行链路

```
用户自然语言
   │
   ├─ TaskManager 建任务（MongoDB，状态 0=排队 1=执行中 2=完成）
   │
   ├─ Planner     拆子任务，生成依赖关系
   │     └─ 每个子任务 → 三步漏斗选工具 → 参数提取
   │
   ├─ ToolUseHub  按工具定义拼 URL + Header(X-API-Key) + Body 发起真实调用
   │
   ├─ SummaryHub  LLM 汇总各步结果，产出自然语言结论
   │
   └─ /api_task_status 轮询返回流程图数据（nodes + edges）
```

耗时环节（LLM 调用、外部接口请求）通过 `ThreadPoolExecutor` 异步执行，接口先返回 `task_id`，前端轮询任务状态，避免请求阻塞。

---

## 快速开始

### 1. 启动基础设施（Milvus + MongoDB）

```bash
docker compose -f docker-compose.infra.yml up -d
docker compose -f docker-compose.infra.yml ps    # 等 milvus 变成 healthy
```

Milvus 走**本地磁盘存储**（`COMMON_STORAGETYPE=local`），不需要 MinIO，少一个容器、启动更快。

### 2. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置密钥

```bash
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

只需填 `model_api_key`（[百炼控制台](https://bailian.console.aliyun.com/) 创建）。其余项按 `.env.example` 默认值即可。

> 注意 `local_mode=1` 会强制使用本机 Milvus(19530) 和本机 MongoDB **27112** 端口（不是 27017），与上面的 compose 对齐。

### 4. 启动服务

开两个终端：

```bash
python mock_server.py     # 模拟被编排的外部系统，监听 127.0.0.1:8080
python app.py             # 主服务，监听 0.0.0.0:5001
```

### 5. 灌入工具数据

```bash
python seed_tools.py
```

把 `api_data/dataset_apis_local.json` 里的 25 个接口写入 MongoDB，并生成向量索引。

### 6. 跑一个任务

```bash
python demo_run.py
```

脚本会先调用 mock 服务的 `/reset` 把数据恢复初始状态，再提交需求并轮询结果，因此**同一段流程可以反复演示**，不受上一次调用的影响。

也可以直接传自己的需求：

```bash
python demo_run.py "帮我查一下订单1的信息"
```

---

## 已验证的执行结果

输入：`帮我查一下订单3现在的状态，如果是待发货就更新为运输中`

平台自动拆成两个子任务并串行执行，约 10 秒完成：

| 步骤 | 选中工具 | 提取参数 | 实际返回 |
|---|---|---|---|
| 1 | 查询订单信息 | `{"orderId": 3}` | `status = 待发货` |
| 2 | 更新订单状态 | `{"orderId": 3, "newStatus": "运输中"}` | `订单 3 状态已从「待发货」更新为「运输中」` |

最终输出：`已处理完成子任务 将订单3的状态更新为「运输中」`

关键在于第 2 步是模型**根据第 1 步的返回值自行决定**要不要执行、以及填什么参数，而不是预先写死的流程。

---

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/register_user` | 注册（字段：`username` / `password` / `confirm`） |
| POST | `/login_user` | 登录，返回 JWT |
| POST | `/api_planning` | 提交自然语言需求，返回 `task_id` |
| POST | `/api_task_status` | 轮询任务状态与流程图数据 |
| POST | `/upload_tool` | 上传 OpenAPI 文档，解析入库（需 `upload_file` 权限） |
| GET | `/get_all_tools` | 查询工具列表 |
| POST | `/delete_tool_by_ids` | 按 ID 删除工具 |

所有业务接口需要请求头 `Authorization: Bearer <access_token>`。

---

## 相对课程原始版本的本地化改造

原始工程按课程环境编写，直接克隆下来无法运行。本仓库做了以下改造：

1. **`docker-compose.infra.yml`**：原 compose 只有 Milvus 三件套且散落在文档目录里，缺 MongoDB。这里合并成一份，端口对齐 `utils/config.py` 的 `local_mode` 分支，并去掉 MinIO 依赖。
2. **`mock_server.py`**：原数据集指向的外部演示服务 `http://121.43.198.13:8080` 已失效（返回登录页 HTML），导致结果总结环节拿不到有效数据。用内存数据复刻了全部 25 个接口，使链路可以完全离线演示。
3. **`api_data/dataset_apis_local.json`**：servers 地址指向本地 mock，其余内容与原文档一致。
4. **配置修复**：`.env` 中的库地址、失效模型名（`qwen-max-0919` → `qwen-max`）等。
5. **`seed_tools.py` / `demo_run.py`**：把数据导入和链路验证固化成脚本，省去手工点接口。

## 目录结构

```
├── app.py                      Flask 入口，路由与线程池调度
├── mock_server.py              本地模拟的外部工具服务
├── docker-compose.infra.yml    Milvus + MongoDB
├── seed_tools.py               工具数据导入
├── demo_run.py                 端到端演示脚本
├── apis/                       工具选型中心、任务规划中心
├── tools/                      工具管理 / 工具调用 / 结果总结
├── prompt/                     提示词模板与按模型分派的工厂
├── param_extraction/           参数提取
├── models/                     LLM 与向量模型封装
├── customize_milvus_wrapper/   Milvus 读写封装
├── entity/                     数据模型
├── use_manager/                用户与权限
└── local_embedding/            本地向量模型微调脚本（可选，默认不用）
```

## 已知限制

- 异步执行用进程内线程池，服务重启会丢失执行中的任务；生产化需要换成外部队列（Celery / RabbitMQ）。
- 会话缓存是进程内字典，多实例部署时 JWT 校验会失效，需要换 Redis。
- 工具调用目前无重试与熔断，外部接口超时会直接落到该子任务失败。
- 流程图数据结构直接复用前端 ECharts 的 `nodes/edges` 格式，接口与展示耦合较紧。
