# Agent Copilot · 自然语言驱动的 API 编排平台

用一句自然语言描述需求，系统自动完成 **任务拆解 → 工具选择 → 参数提取 → 接口调用 → 结果总结** 全流程，并把每一步执行的接口调用实时转换成可视化流程图返回前端。

> 个人独立项目 · 2026.08 - 2026.10

## 核心流程

```
用户输入（自然语言）
   └─ POST /api_planning ──> 建任务，返回 task_id（异步，不阻塞）
        └─ 线程池 _process_task
             ├─ 1. 任务拆解      gen_root_task      判断单任务 / 多任务，拆出子任务描述
             ├─ 2. 工具选择      三层漏斗：Milvus 向量召回 → reranker 精排 → LLM 裁决
             ├─ 3. 参数提取      从自然语言中抽取接口参数，缺失则逆向补参
             ├─ 4. 安全校验      防注入校验，通过后才允许调用
             ├─ 5. 工具调用      按 OpenAPI 参数位置拼装 path / query / body 发起 HTTP
             └─ 6. 结果总结      LLM 生成自然语言摘要，调用链转流程图节点/边写库
   └─ POST /api_task_status（前端 2s 轮询）──> 返回 nodes / edges / isEnd
```

## 关键设计

**三层工具选型漏斗**（避免把全量工具塞进提示词）
1. Milvus 向量召回 `topK * 2` 个候选工具
2. reranker 精排（支持本地 BGE 模型 / 远程 Qwen rerank），取 `topK`
3. LLM 在候选中裁决出唯一工具

**缺参逆向补参**
必填参数缺失时不直接失败，而是：生成"查参子任务" → 二次工具选型 → 调用参数查询接口 → 回填参数 → **二次安全校验** → 再执行原调用。流程图上会额外生成反向补参子节点。

**异步任务 + 轮询**
`/api_planning` 只负责建任务并丢进线程池，立即返回 `task_id`；执行过程写 MongoDB，前端每 2 秒轮询 `/api_task_status` 拿中间态，逐节渲染流水线。

**调用链即记忆**
`api_chain` 同时承担三个角色：循环变量、LLM 上下文来源、前端流程图数据源。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3 / Flask / JWT（PyJWT）/ TTLCache / ThreadPoolExecutor |
| 存储 | MongoDB（工具、任务、用户）、Milvus（工具向量库） |
| 模型 | 通义千问 qwen-max（OpenAI 兼容接口）、gte-rerank / 本地 BGE reranker、本地 embedding |
| 前端 | React 19 / Ant Design 5 / @ant-design/x / relation-graph（流程图）/ axios |
| 部署 | Docker Compose（Milvus + MongoDB 基础设施）、Flask 内置服务 |

## 目录结构

```
.
├── backend/                    # Flask 后端（端口 5001）
│   ├── app.py                  # 入口：10 个 REST 接口 + JWT 鉴权 + 线程池
│   ├── apis/                   # 编排核心：api_planning_hub（拆解/补参/调用链）
│   │   └── api_selection_hub.py# 工具选型三层漏斗
│   ├── tasks/                  # 任务拆解、参数查询任务生成、任务 CRUD
│   ├── tools/                  # 工具管理、工具调用、结果总结
│   ├── param_extraction/       # 参数提取与校验
│   ├── prompt/                 # 提示词模板（通用 / qwen / 模型专用）
│   ├── entity/                 # 数据实体（Tool / Task / User）
│   ├── models/                 # LLM、embedding、reranker 客户端封装
│   ├── customize_milvus_wrapper/  # Milvus 向量库封装
│   ├── mock_server.py          # 业务接口 mock（端口 8080）
│   └── docker-compose.infra.yml   # Milvus + MongoDB
├── frontend/                   # React 前端（端口 3000）
├── scripts/                    # 一键启动脚本
└── 启动项目.bat                 # Windows 一键启动（基础设施 + 三个服务）
```

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/register_user` | 注册，写入默认权限 |
| POST | `/login_user` | 登录，签发 JWT（1h）并写入会话缓存 |
| POST | `/logout_user` | 登出，清除令牌 |
| GET | `/get_all_tools` | 查询全部工具 |
| POST | `/upload_tool` | 上传 OpenAPI 文档，解析入库并生成向量 |
| POST | `/insert_tool` | 新增单个工具 |
| POST | `/delete_tool_by_ids` | 按 ID 批量删除工具 |
| GET | `/delete_all_tool` | 清空工具库 |
| POST | `/api_planning` | 提交自然语言任务，返回 `task_id` |
| POST | `/api_task_status` | 轮询任务状态，返回流程图节点/边 |

## 快速开始

### 方式一：一键启动（Windows）

```bat
启动项目.bat
```

自动完成：Docker 基础设施 → 后端 5001 → mock 8080 → 前端 3000，日志写入 `logs\`。

### 方式二：手动启动

```bash
# 1. 基础设施（Milvus + MongoDB）
docker compose -f backend/docker-compose.infra.yml up -d

# 2. 后端
cd backend
cp .env.example .env          # 填入 DashScope API Key
.venv/Scripts/python.exe app.py          # Windows
# 或  python app.py

# 3. 业务 mock 接口
.venv/Scripts/python.exe mock_server.py

# 4. 前端
cd ../frontend
npm install
npm start
```

打开 `http://localhost:3000`，注册登录后即可对话。

### 环境变量

参考 `backend/.env.example`：

| 变量 | 说明 |
|---|---|
| `model_api_key` | 阿里云百炼 DashScope API Key |
| `model_base_url` / `model_name` | 模型地址与名称（默认 qwen-max） |
| `milvus_uri` / `milvus_db_name` | Milvus 连接与库名 |
| `mongo_host` / `mongo_port` / `mongo_db` | MongoDB 连接 |
| `topK` | 工具召回数量 |
| `SECRET_KEY` / `JWT_ALGORITHM` | JWT 签名配置 |
| `local_mode` | 1 = 强制使用本机 Milvus + MongoDB |

> `.env` 已被 `.gitignore` 排除，仓库内只保留不含密钥的 `.env.example`。

## 权限说明

接口通过 `require_permission` 装饰器按函数名校验 `user_authority`。权限在登录时写入 JWT 与会话缓存，**修改权限后需重新登录**才生效。
