# Memory Palace OS

**景区运营智能应急响应与经验传承系统**

文档核对日期：2026-10-07。目录、运行入口和接口说明以当前 `master` 源码为准。

支持景区事件上报、Agent 处置建议、任务与审批闭环、SOP 检索，以及专家访谈和经验资产发布。正式客户端包括管理台、员工助手、景区运行准备入口与企微流程模拟器。

---

## 企业 MVP（正式入口）

当前交付面是正式客户端，不是动画或播放器。正式链路使用 Nginx、App、PostgreSQL + pgvector、Redis Streams、本地 `BAAI/bge-m3`（1024 维）与真实 `deepseek-flash`。

`master` 是 GitHub 的默认发布分支。接手项目或准备发布前，先阅读 [`REPRODUCE.md`](REPRODUCE.md)，并以仓库锁定的 Python 3.11、Node 24、pnpm 11、TEI CPU 1.9.4 以及依赖锁定文件为准。

Windows + Docker Desktop 快速启动：

```powershell
$envFile = 'C:\secure\memory-palace-uat.env'
scripts\mvp.cmd install -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
powershell -ExecutionPolicy Bypass -File scripts\set_deepseek_secret.ps1 -VolumeName memory-palace-secrets
powershell -ExecutionPolicy Bypass -File scripts\set_scenic_account_secret.ps1 -VolumeName memory-palace-secrets
scripts\mvp.cmd start -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd verify -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
```

启动成功后访问 [http://localhost:8090/admin/](http://localhost:8090/admin/)。系统不提供公开默认密码；使用部署 EnvFile 初始化的管理员账号登录，并在交付前完成密码轮换。

- [企业 MVP 交付 PRD](PRD-memory-palace-enterprise-mvp.md)
- [统一员工助手与经验资产 PRD](PRD-memory-palace-unified-agent-experience-mvp.md)
- [2026-09-27 UAT 执行报告](docs/verification/unified-agent-uat/UAT-20260927T083848Z-6FBDFEF6/execution-report.md)
- [前端源码构建与入口切换](docs/operations/frontend-source-build.md)
- [备份、恢复与诊断手册](docs/operations/mvp-backup-restore.md)

> 当前仓库目标是企业 MVP 发布候选。2026-09-27 的内部 UAT 记录 30/30 必需旅程通过，其中 E2E-15/16 的部分模型决策使用报告声明的测试替身；不代表全部场景均为真实模型调用。客户 UAT、24 小时连续运行与客户签收仍需在目标环境完成。真实企微回调和发送当前按项目策略禁用，展示使用内部模拟器；短信和语音缺少配置时不会伪造发送成功。7 月的 UAT 证据已标记为历史快照。

## 本地景区模拟环境

Windows + Docker Desktop：

```powershell
Copy-Item .env.example .env
$env:BGE_M3_CACHE_DIR = 'D:\memory-palace-models\huggingface'
powershell -ExecutionPolicy Bypass -File scripts/scenic.ps1 prepare-model -ModelCache $env:BGE_M3_CACHE_DIR
powershell -ExecutionPolicy Bypass -File scripts/set_deepseek_secret.ps1 -VolumeName memory-palace-secrets
powershell -ExecutionPolicy Bypass -File scripts/set_scenic_account_secret.ps1 -VolumeName memory-palace-secrets
powershell -ExecutionPolicy Bypass -File scripts/scenic.ps1 start -ModelCache $env:BGE_M3_CACHE_DIR
```

在 `.env` 中设置 PostgreSQL、JWT 和管理员强密码，确认 `MEMORY_PALACE_SECRETS_VOLUME` 与两个密钥脚本的卷名相同。正式默认嵌入由 TEI CPU 容器提供，模型缓存只读挂载；切换本地嵌入回退路径需按部署 profile 文档配置。

演示使用三个独立浏览器会话：

1. 以 `simulation-ops` 登录 `http://localhost:8090/operations/scenic/`，准备 `rain_vehicle_east_gate`，单步 2 秒产生雨后复检和 12 号车异常。
2. 以王芳 `wangfang` 登录 `/admin/`，在景区指挥中心将设备告警转为 P1 运营事件。
3. 以李明 `liming` 登录 `/assistant/`，在“共享景区态势”上传右后轮现场图并填写文字说明。
4. 回到 `/admin/`，真实检索雨后复运 SOP，生成检修任务与高风险审批；王芳批准继续停运 12 号车并启用 7 号备用车。
5. 以陈雨 `chenyu` 登录 `/assistant/`，开始检修任务并提交结构化检查结论。
6. 在运行准备入口单步至第 30 秒；`/admin/` 出现东门客流告警，创建分流任务。
7. 李明在 `/assistant/` 接单并提交分流措施和风险状态；运行准备入口再推进到第 90 秒，使设备与客流告警恢复。
8. 王芳在 `/admin/` 解除风险并关闭事件；在事件卷宗核对信号、告警、任务、审批、通知送达、接单、现场回执、SOP 命中与审计序号。
9. 以经理账号打开 `/simulator/wecom/`，选择对应员工会话，核对内部 outbox 的“已送达 → 已接单 → 已回执”。短信和语音仍显示 `NOT_CONFIGURED`。

`/admin/`、`/assistant/` 与 `/simulator/wecom/` 只投影 PostgreSQL 中的同一事件状态；模拟控制只存在于受保护的运行准备入口。旧 `/demo/` 保留兼容，但不是新状态源。

---

## 业务闭环

现场消息通过统一入口写入 PostgreSQL 并进入 Redis Streams；Agent 结合来源证据生成处置建议。管理人员审核高风险动作、分派任务，员工接单并提交回执；事件关闭时核对任务、审批、风险和卷宗证据。模型延迟取决于网络与运行环境，处理失败会记录错误和恢复状态。

专家通过结构化访谈形成经验卡，经过确认、审查、授权和发布后进入检索；现场处置反馈与知识缺口继续回到管理工作台。

---

## Agent 与业务能力

景区建议由 `IncidentCommand` 编排 ContextTrigger、Router、MemoryOps 和 Commander。访谈、经验资产、巡检和任务中心由对应技能与业务服务配合完成。

**Agent 矩阵：**

| Agent | 职责 | 触发方式 |
|-------|------|----------|
| **ContextTrigger** | 情境触发 · 优先级与 SLA 判断 | 现场消息 / Watcher |
| **Router** | 意图识别 · Agent 路由 | 所有消息 |
| **Commander** | P0/P1 处置建议 · 任务与审批编排 | 现场事件 |
| **MemoryOps** | RAG 经验检索 · 来源归因 · SOP 草稿萃取 | 消息链路 / 知识检索 |
| **Persona** | 授权经验问答 · 来源展示 | 正式客户端 |
| **PersonaExtract** | 老员工结构化访谈萃取 · 逻辑条目提取 | 管理后台 / 访谈 API |
| **Watcher** | SLA 巡检 · 发现分派 · 闭环审计 | 手动 / 定时任务 |
| **TodoWrite** | 复杂目标 → 可恢复任务依赖图 | 任务中心 |

角色与 `venue_id` 限制数据访问，高风险动作经过审批；任务图、消息运行、建议运行和审计保存在 PostgreSQL，启动恢复与队列重试由运行时服务处理。相关实现位于 `core/permissions.py`、`core/task_graph.py`、`core/runtime_recovery.py` 和 `scenic/advice_runs.py`。

---

## 技术架构

`IncidentCommand` 编排四个景区 Agent，pydantic-ai 校验结构化输出，LiteLLM 负责模型调用。建议运行支持 Redis 与 Hatchet 模式；Hatchet 编排与人工中断需启用 `agent-runtime` profile 并配置对应运行模式。

```text
正式客户端 / 现场端 / 受保护的景区运行入口
            ↓
          Nginx
            ↓
 FastAPI（Auth / JWT / venue_id / Canonical Ingress）
            ↓  先写 PostgreSQL，再入队
 Redis Streams（队列、重试与死信）
            ↓
 Worker + Hatchet（编排与人工中断）
            ↓
 ┌──────────────────────────────────────┐
 │  IncidentCommand（唯一深 seam）        │
 │  编排 · 门禁 · 超时 · 失败降级 · 幂等   │
 └──────────────────────────────────────┘
     ↓        ↓         ↓         ↓
 ContextTrigger  Router  MemoryOps  Commander
        （同一模型：deepseek-flash）
            ↓
 LiteLLM（进程内模型网关）
            ↓
 OpenTelemetry SDK / OTLP → Jaeger（链路下钻，可选）

数据与运行平面
 PostgreSQL（唯一业务事实源：事件、卷宗、任务、审批、经验、审计、llm_call_logs）
 PostgreSQL pgvector（1024 维；TEI bge-m3 嵌入，可选 TEI 重排）
 Redis Streams（消息与建议运行队列）
 external secret volume（DeepSeek Key）

质量门禁
 DeepEval 4.2.x
```

默认 Compose 栈包含 App、PostgreSQL、Redis、Nginx 和 TEI 嵌入服务；`tei-reranker`、`agent-runtime`、`tracing` 等按需启用。版本、资源预算和启动顺序见 [部署 profiles](docs/architecture/scenic-agent-deployment-profiles.md)。

技术栈与选型理由见 [ADR-0018](docs/adr/0018-agent-chain-as-scenic-incident-trunk.md) 与
[ADR-0019](docs/adr/0019-agent-runtime-stack-selection.md)；运行时差距与风险见
[docs/architecture/agent-runtime-gap-review.md](docs/architecture/agent-runtime-gap-review.md)。

pgvector 里应当有哪些数据、来自哪张事实表、如何核验，见 [docs/vector-data-contract.md](docs/vector-data-contract.md)；
可用 `uv run --no-project --python 3.11 --with-requirements requirements.lock python scripts/verify_vector_data.py` 检查数据契约。

现场演示（人工操作）看 [docs/operations/scenic-demo-startup.md](docs/operations/scenic-demo-startup.md)：
先执行 `powershell -ExecutionPolicy Bypass -File scripts/scenic-demo-start.ps1` 启动完整栈，再执行
`powershell -ExecutionPolicy Bypass -File scripts/scenic-demo-open.ps1` 打开 5 个已登录入口，最后由人操作；
15 步流程见 [docs/operations/scenic-demo-runbook.md](docs/operations/scenic-demo-runbook.md)。
SOP/知识导入走正式发布链路：
`uv run --no-project --python 3.11 --with-requirements requirements.lock python scripts/import_sops.py --input artifacts/knowledge/sops-curated.json --base-url http://127.0.0.1:8090`；
公开来源检索可用 `uv run --no-project --python 3.11 --with-requirements requirements.lock python scripts/collect_knowledge_sources.py`（AnySearch，匿名可用，配置 `ANYSEARCH_API_KEY` 提升配额）。

---
## 目录结构

```
.
├── main.py                  # FastAPI 应用入口；生产和本地 uvicorn 都从这里启动
├── src/memory_palace/
│   ├── api/
│   │   ├── v1/endpoints/    # admin / auth / attachments / assistant / channels / experiences /
│   │   │                     # knowledge / management / messages / scenic / sessions /
│   │   │                     # skills / watcher / workflows
│   │   └── v2/              # 已挂载的空路由占位，当前没有公开 v2 业务端点
│   ├── agent_contracts/     # Agent 输入、输出和模型契约
│   ├── config/              # 配置、Secret、环境校验和功能注册表
│   ├── core/                # 消息、队列、任务、权限、租户、审计和运行恢复
│   ├── demo/                # DEMO_MODE 场景与适配器（不作为正式数据源）
│   ├── incident/            # IncidentCommand 与四 Agent 生产主干
│   ├── knowledge/           # 来源、SOP、经验资产和 PostgreSQL pgvector
│   ├── metrics/             # Prometheus 指标和告警定义
│   ├── operations/          # 运行诊断、UAT bootstrap 和展示数据
│   ├── scenic/              # 景区事件、建议运行、实时视图和 Redis/Hatchet 编排
│   ├── skills/              # commander / context_trigger / memory_ops / persona /
│   │                         # persona_extract / router / todo / watcher
│   ├── static/              # Python 包占位；实际页面和资源在根目录 static/
│   └── tools/               # LLM、嵌入、企微、数据库和工具执行器
├── deploy/                  # Docker Compose、Dockerfile 和部署 profile
├── frontend/
│   ├── apps/                # console / field / integration / operations
│   ├── packages/            # api-client / design-tokens / domain-ui
│   ├── e2e/                 # 前端端到端测试
│   └── scripts/             # OpenAPI 类型和离线构建脚本
├── static/                  # 已构建的管理台、员工端、运营端和企微模拟器资源
├── scripts/                 # MVP 生命周期、景区演示、导入和验证命令
├── docs/                    # ADR、架构图、运维手册和 UAT 证据
├── evals/                   # Scenic Agent contract/live eval 数据集
├── artifacts/knowledge/     # 可移植知识与 SOP 夹具
├── tests/                   # unit / integration / js / powershell 测试
├── openspec/                # 规格和变更提案
├── graphify-out/            # 生成的代码图和缓存（已标记为 Linguist generated）
├── pyproject.toml           # Python 包和工具配置
├── requirements.lock        # 生产与测试的 Python 依赖固定解析结果
├── requirements*.txt        # 依赖输入及 eval/原型/本地嵌入扩展
└── README.md / REPRODUCE.md # 使用说明与可复现交付说明
```

该树列出维护入口，省略单文件和辅助目录。`artifacts/knowledge/` 是本机保留的可移植夹具目录：若 Git clone 后不存在，需从交付包取得，不能用运行数据库替代。`.venv`、`node_modules`、数据库、日志和模型缓存不属于源码目录。

---

## 兼容本地开发运行（非企业 MVP 入口）

### 前置

- Python 3.11（以 `requirements.lock` 和 Dockerfile 为准）
- `uv` 和已配置的 PostgreSQL、Redis、TEI 服务
- 正式模式的管理员、景区账号及 DeepSeek 凭据；详细变量以 `.env.example` 为准

### 安装

```bash
cd memory-palace-os
cp .env.example .env
# 编辑 .env 填入非 LLM 密钥配置

uv run --no-project --python 3.11 --with-requirements requirements.lock \
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

数据库表和正式运行依赖由 `main.py` 的 lifespan 在启动时初始化；不要再调用已经移除的 `init_db()`。

### Docker 持久化 DeepSeek 密钥

Docker 部署不把 DeepSeek API Key 写入 `.env`、镜像层或容器环境变量。首次配置或轮换密钥时运行一次：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/set_deepseek_secret.ps1
```

脚本通过隐藏输入和原子替换把密钥保存到外部 Docker volume `memory-palace-secrets`，并自动重启正在使用该卷的应用容器。之后执行 `docker compose up -d --force-recreate`、重建应用镜像或重启 Docker Desktop 都会自动复用该密钥；只有主动删除外部 volume 或轮换密钥时才需要再次运行脚本。

非 Docker 的本地 Python 运行可通过 `DEEPSEEK_API_KEY` 或 `DEEPSEEK_API_KEY_FILE` 提供同一密钥。

### 验证

```powershell
scripts\mvp.cmd status -Project memory-palace-uat
scripts\mvp.cmd verify -EnvFile C:\secure\memory-palace-uat.env -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd doctor -Project memory-palace-uat
```

正式客户端：`http://localhost:8090/admin/`。账号和密码来自部署初始化，不写入 README、镜像或交付截图。

### 管理后台功能

访问 `/admin/` 进入正式企业运营工作台。当前 Vue 客户端源码位于 `frontend/apps/console/`，主要业务能力包括：

| 模块 | 说明 |
|------|------|
| **运营工作台** | 真实事件、任务、SLA、Agent 与更新时间统计 |
| **现场事件** | 实时上报、历史补录、筛选、详情、处置与关闭 |
| **消息与会话** | 会话列表、详情、历史、状态和关闭 |
| **任务中心** | TodoWrite 分解、依赖、分配、执行、失败与恢复 |
| **审批中心** | 高风险动作申请、批准、拒绝和执行结果 |
| **推送与动作日志** | 渠道、收件人、状态、错误、采纳和并发冲突 |
| **知识库** | 版本化知识 CRUD、导入、索引重建与语义检索 |
| **数字分身** | Persona 创建、访谈恢复、授权问答、搜索与删除 |
| **鹰眼巡检** | 策略、手动/定时运行、发现分派、关闭和停用 |
| **SOP 中心** | 草稿、提审、驳回、修订、发布与再次检索 |
| **用户与场地** | 用户生命周期、角色与 `venue_id` 管理 |
| **系统设置** | 非敏感设置、模型和外部集成状态 |
| **运维诊断** | 健康、队列、死信、热重载、Trace 和审计 |

专家经验流程：管理端登记专家与授权、创建访谈 → 员工端接受并回答结构化问题 → 生成、修订和确认经验卡 → 管理端审查与发布 → 授权检索与反馈。旧 Persona 接口仍保留；正式经验资产流程见 [页面与入口说明](docs/product/unified-agent-page-map.md)。

---

## 配置说明

### 部署 EnvFile 核心变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | ✅ | PostgreSQL 数据库与凭据 |
| `MEMORY_PALACE_JWT_SECRET` | ✅ | JWT 签名密钥，使用高熵随机值 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | ✅ | 首次管理员账号，不使用演示密码 |
| `DEFAULT_VENUE_ID` / `DEFAULT_VENUE_NAME` | ✅ | 初始租户与场地 |
| `HTTP_PORT` | ✅ | Nginx 对外端口，景区演示默认 `8090`（8080 常被其他本地项目占用） |
| `MEMORY_PALACE_SECRETS_VOLUME` | ✅ | DeepSeek 外部 Secret 卷名称 |
| `BGE_M3_CACHE_DIR` | ✅ | TEI 使用的本地模型缓存绝对路径 |
| `FRONTEND_V2_APPS` | 选填 | Vue 客户端入口选择：`console,field,integration,operations` |
| `ADVICE_EXECUTION_MODE` | 选填 | `redis`（默认）或 `hatchet`；后者需 `agent-runtime` profile 与凭据 |
| `WECHAT_*` / `SMS_*` / `VOICE_*` | 选填 | 缺少真实供应商配置时安全禁用 |

DeepSeek API Key 不写入 EnvFile，而是通过 `scripts/set_deepseek_secret.ps1` 一次性注入外部 Docker volume。所有生成式调用固定使用 `deepseek-flash`，正式 MVP 不允许通过 `DEMO_MODE` 或 Mock 绕过模型。

---

## API 端点

### 运行与 API 入口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/health` | 轻量健康页或 JSON |
| `GET` | `/ready` | 依赖就绪检查 |
| `POST` | `/api/v1/auth/login` | 登录并获取访问令牌 |
| `POST` | `/api/v1/auth/refresh` | 刷新访问令牌 |
| `GET` | `/api/v1/auth/me` | 当前用户身份 |
| `GET` | `/api/v1/assistant/work` | 员工工作台与任务 |
| `POST` | `/api/v1/assistant/attachments` | 员工端附件上传 |
| `POST` | `/api/v1/channels/simulator/messages` | 模拟器消息入口 |
| `GET` | `/api/v1/channels/simulator/sessions/{session_id}/outbox` | 会话通知送达与回执 |
| `POST` | `/api/v1/messages/` | 接收消息并返回运行 ID |
| `GET` | `/api/v1/messages/{message_id}` | 查询消息运行状态 |
| `GET` | `/api/v1/sessions/` | 会话列表 |
| `GET` | `/api/v1/skills/` | 已注册技能 |
| `GET` | `/api/v1/scenic/snapshot` | 景区当前态势快照 |
| `POST` | `/api/v1/scenic/commands` | 提交受保护的景区命令 |
| `GET` | `/api/v1/scenic/stream` | 景区态势 SSE |
| `GET` | `/api/v1/admin/health` | 管理员依赖健康状态 |
| `GET` | `/api/v1/admin/dashboard` | 管理后台统计 |
| `GET` | `/api/v1/admin/events` | 事件卷宗列表 |
| `GET` | `/api/v1/admin/tasks` | 任务列表 |
| `GET` | `/api/v1/admin/approvals` | 待审批请求 |
| `GET` | `/api/v1/admin/diagnostics` | 运维诊断 |
| `GET` | `/api/v1/admin/knowledge` | 知识文档管理 |
| `GET` | `/api/v1/admin/sops` | SOP 生命周期管理 |
| `GET` | `/api/v1/admin/experts` | 专家名录 |
| `GET` | `/api/v1/admin/experience-interviews` | 专家访谈 |
| `GET` | `/api/v1/admin/experience-cards` | 经验卡审查与发布 |
| `GET` | `/api/v1/assistant/experience` | 员工经验与访谈入口 |
| `GET` | `/demo/scenarios` | 仅 `DEMO_MODE=true` 时可用的演示场景 API |
| `GET` / `POST` | `/webhook/v1/wechat` | 真实企微回调当前禁用，返回 503 |

表中列出常用端点；完整定义以 `src/memory_palace/api/v1/router.py` 及 `endpoints/` 中的路由为准。
`/api/v2` 当前只保留空路由占位，没有稳定公开端点；正式客户端使用 `/api/v1` 和受保护的页面入口。

---

## 监控指标

```
memory_palace_http_requests_total{method, endpoint, status_code}
memory_palace_http_request_duration_seconds{method, endpoint}
memory_palace_queue_depth{queue_name}
memory_palace_queue_messages_processed_total{queue_name, status}
memory_palace_llm_requests_total{provider, model, status}
memory_palace_llm_tokens_total{provider, model, token_type}
```

健康检查：
```
GET /health          → 进程健康页或 JSON
GET /ready           → 依赖就绪检查
GET /api/v1/admin/health → 管理员依赖、队列和 pgvector 健康状态
```

---

## 测试

```powershell
# 运行全部测试
uv run --no-project --python 3.11 --with-requirements requirements.lock pytest -q

# 运行景区 Agent contract eval
uv run --no-project --python 3.11 --with-requirements requirements.lock `
  python evals/scenic_agent/run_deepeval.py --mode contract `
  --report artifacts/scenic-agent-eval/contract-report-local.json

# 只跑单元测试
uv run --no-project --python 3.11 --with-requirements requirements.lock pytest -q tests/unit
```

`contract` 检查金标准数据与输出约束，不调用真实模型，也不需要 DeepEval 包。真实模型与裁判评测使用独立 eval 环境；`requirements-eval.txt` 中的 DeepEval 4.2.3 与当前生产锁的 Click 8.5.0 约束冲突，不能直接叠加安装。升级或重新锁定 eval 依赖需单独验证。

---

## 常见问题

**Q: 企微回调收不到消息**
- 当前真实企微回调与发送按项目策略禁用；演示与验证使用 `/simulator/wecom/` 内部渠道。
- 配置企微凭据不会自动启用真实回调，需另行实现并验证集成切换。

**Q: 服务启动报错**
- 运行 `scripts\mvp.cmd doctor -Project <project>` 检查 Docker、容器、卷和依赖健康。
- 确认 `-EnvFile` 指向仓库外的受限文件，并包含必填部署变量。
- 确认外部 Secret 卷存在且 `deepseek_api_key` 非空。

**Q: LLM 调用失败**
- 在运维诊断页查看真实 `deepseek-flash` 调用、重试和 Trace。
- 检查外部 Secret 卷、网络和 DeepSeek 账户状态。
- 失败路径进入重试、熔断或人工继续，不返回伪造成功结果。

---

## 企业 MVP 运维

Windows + Docker Desktop 的正式生命周期入口：

```powershell
$envFile = 'C:\secure\memory-palace-uat.env'
scripts\mvp.cmd install -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd start -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd status -Project memory-palace-uat
scripts\mvp.cmd migrate -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd verify -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd doctor -Project memory-palace-uat
scripts\mvp.cmd backup -Project memory-palace-uat
scripts\mvp.cmd logs -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets -Tail 200
scripts\mvp.cmd upgrade -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd restart-app -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd stop -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
```

Docker Desktop 无法连接镜像仓库、但固定版本镜像已在本机缓存时，`install` 和 `upgrade` 可显式增加 `-Offline`；它只跳过拉取，不放宽版本、迁移或健康门禁。

`restart-app` 是恢复旅程的固定范围入口：只重启 App，等待其重新健康，并核对 PostgreSQL、Redis、pgvector 数据与 Nginx 均未被清理；命令会输出 App 重启前后的运行标识，供诊断页核验。

`stop`、重启 Docker Desktop、重建 App/Nginx 镜像都保留数据卷和外部 Secret 卷。恢复必须指定新的 Compose project、独立 Secret 卷、环境文件和精确目标确认。完整安全说明见
[企业 MVP 备份、恢复与诊断](docs/operations/mvp-backup-restore.md)。

---

## 发布与后续维护

- 功能开发使用独立分支，通过 Pull Request 合并到 `master`；合并前确认 `git status`，不要把 `.env`、Docker secrets、数据库卷、日志、模型缓存、依赖目录或运行时输出加入提交。
- 生成的代码图和产品单页已通过 `.gitattributes` 标记为 GitHub Linguist 生成文件，避免它们扭曲语言占比；模板和生成脚本仍保留在仓库中。
- 代码变更后运行受影响的 pytest、契约 eval 和 `git diff --check`。真实 DeepSeek live eval 只在凭据通过外部 secret 注入时运行，报告不要把本机模型响应当作新的金标准。
- 数据集保存在 `evals/`，可移植知识夹具保存在 `artifacts/knowledge/`；通过正式 HTTP API 或已有导入脚本更新，不直接写入本机数据库文件。

## License

MIT
