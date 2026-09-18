# Memory Palace OS

**景区运营智能应急响应与经验传承系统**

基于 OpenClaw 多Agent架构启发，融合 Harness 式自主Agent生命周期管理，打造景区运营场景下的**智能体协作平台**。

---

## 企业 MVP（正式入口）

当前交付面是正式客户端，不是动画或播放器。正式链路使用 Nginx、App、PostgreSQL + pgvector、Redis Streams、本地 `BAAI/bge-m3`（1024 维）与真实 `deepseek-flash`。

Windows + Docker Desktop 快速启动：

```powershell
$envFile = 'C:\secure\memory-palace-uat.env'
scripts\mvp.cmd install -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
powershell -ExecutionPolicy Bypass -File scripts\set_deepseek_secret.ps1 -VolumeName memory-palace-secrets
scripts\mvp.cmd start -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
scripts\mvp.cmd verify -EnvFile $envFile -Project memory-palace-uat -SecretsVolume memory-palace-secrets
```

启动成功后访问 [http://localhost:8090/admin/](http://localhost:8090/admin/)。系统不提供公开默认密码；使用部署 EnvFile 初始化的管理员账号登录，并在交付前完成密码轮换。

- [企业 MVP 交付 PRD](PRD-memory-palace-enterprise-mvp.md)
- [内部 UAT 与发布就绪报告](docs/verification/mvp-uat-20260728/internal-uat-release-readiness.md)
- [浏览器 QA 报告](docs/verification/mvp-uat-20260728/browser-qa-report.md)
- [备份、恢复与诊断手册](docs/operations/mvp-backup-restore.md)

> 当前仓库目标是企业 MVP 发布候选。开发团队内部 UAT 不替代客户 UAT；24 小时连续运行与客户签收仍需在目标环境完成。企微、短信和语音未配置时保持 `DISABLED_REQUIRES_CONFIG`，不会伪造发送成功。旧 `/demo` 仅保留为历史开发资产，不是交付入口。

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

在 `.env` 中设置 PostgreSQL、JWT 和管理员强密码。模型缓存由容器只读挂载，不进入 Git 或应用镜像。CPU 是默认路径；具备 CUDA 环境时可显式设置 `EMBEDDING_DEVICE=cuda`。

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

## 核心定位

当员工在企微群发"有人晕倒了"，系统 30 秒内自动完成：**P0 事件识别 → SOP 指令下发 → 责任人通知 → 全链路记录**。

这不是一个聊天机器人，而是一个**多Agent协作的智能体网络**——每个 Agent 各司其职，从上下文感知到经验检索，从推理决策到推送生成，整个过程无需人工介入，且全程可审计、可干预、可追溯。

---

## 架构哲学

### OpenClaw 式多Agent协作

```
企微消息
    ↓
┌──────────────────────────────────────────────────────────────┐
│                     Orchestrator (主控)                       │
│  意图分发 · SLA 记录 · Agent 调度 · 上下文管理                │
└──────────────────────────────────────────────────────────────┘
    ↓
┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────────┐
│  Router │→│ Commander│→│ Memory Ops│→│  Persona   │
│ (情境感知)│  │ (SOP执行) │  │ (经验检索) │  │ (数字分身)  │
└─────────┘  └──────────┘  └───────────┘  └────────────┘
                                           ↑
              ┌────────────────────────────┘
              ↓
┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────────┐
│ Watcher │  │ TodoWrite │  │(主动监控) │  │(任务分解)   │
└─────────┘  └──────────┘  └───────────┘  └────────────┘
```

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

### 四层上下文压缩 (Token 防火墙)

```
┌─────────────────────────────────────────────────────┐
│                   LLM Context                       │
├─────────────────────────────────────────────────────┤
│  Tier 0 (Hot)   │ 最近 10 条 · 完整 fidelity        │
├─────────────────┼───────────────────────────────────┤
│  Tier 1 (Warm)  │ 被 evict 消息的 LLM 摘要          │
├─────────────────┼───────────────────────────────────┤
│  Tier 2 (Cold)  │ 会话级叙事摘要 · 50 轮触发        │
└─────────────────┴───────────────────────────────────┘
```

### 权限引擎 (企业级安全边界)

| Level | 名称 | 行为 |
|-------|------|------|
| **FREE** | 直接执行 | `search_memory`, `get_context` |
| **LOGGED** | 执行+审计 | `write_memory`, `update_session` |
| **APPROVAL** | 需审批 | `send_sms`, `send_alert`, `send_wechat_message` |

```
工具调用 → 权限检查 → [APPROVAL] → 挂起 → 微信通知 Admin → 等待审批 → 执行
```

### 任务依赖图 (Docker 重启不死)

```python
# 复杂目标自动分解为任务图
goal: "生成月报并发送"
    ↓ TodoWrite Skill
task_1: 收集数据 ──→ task_2: 生成报告 ──→ task_3: 发送邮件
              │              │
              └────── A 失败，B 挂起 ──────┘
                            ↓
              Docker 重启后自动恢复 PENDING 任务
```

### 工作区隔离 (文件系统沙盒)

```
data/workspaces/{task-id}/
├── input/       # 任务输入
├── output/      # 生成输出
├── temp/        # 临时文件 (完成时清理)
└── metadata/    # 元数据

路径遍历攻击 → ValueError: 路径逃逸检测
```

---

## 技术架构

景区正式主干是 **Agent 主干化**：`IncidentCommand` 是编排四个 agent 的唯一深 seam，Hatchet 负责
编排与人工中断，pydantic-ai 承载四 agent 契约，LiteLLM 作为进程内模型网关。

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
 PostgreSQL pgvector（1024 维；TEI 承载 bge-m3 嵌入与 bge-reranker-base 重排）
 Redis Streams（消息与建议运行队列）
 external secret volume（DeepSeek Key）

质量门禁
 DeepEval 4.2.x
```

技术栈与选型理由见 [ADR-0018](docs/adr/0018-agent-chain-as-scenic-incident-trunk.md) 与
[ADR-0019](docs/adr/0019-agent-runtime-stack-selection.md)；运行时差距与风险见
[docs/architecture/agent-runtime-gap-review.md](docs/architecture/agent-runtime-gap-review.md)。

pgvector 里应当有哪些数据、来自哪张事实表、如何核验，见 [docs/vector-data-contract.md](docs/vector-data-contract.md)；
可用 `uv run --no-project --with "psycopg[binary]" python scripts/verify_vector_data.py` 检查数据契约。

现场演示（人工操作）看 [docs/operations/scenic-demo-runbook.md](docs/operations/scenic-demo-runbook.md)：
先用 `uv run --with playwright python scripts/scenic_demo_launcher.py` 打开并按角色登录好各入口，再由人操作。
SOP/知识导入走正式发布链路：`python scripts/import_sops.py --input artifacts/knowledge/sops.json`；
公开来源检索可用 `python scripts/collect_knowledge_sources.py`（AnySearch，匿名可用，配置 `ANYSEARCH_API_KEY` 提升配额）。

---
## 目录结构

```
src/memory_palace/
├── api/
│   ├── v1/endpoints/       # admin / sessions / messages / skills
│   └── v2/                 # dispatch / context / handoff
├── config/                 # 配置加载 & 环境校验
├── core/
│   ├── orchestrator.py     # 主控调度器
│   ├── gateway.py           # 企微回调入口
│   ├── skill_base.py       # Agent/Skill 基类
│   ├── context_tier.py      # [Phase 1] 三层上下文压缩
│   ├── agent_memory.py      # [Phase 1] Agent 内存隔离
│   ├── permissions.py       # [Phase 2] 权限引擎
│   ├── task_graph.py        # [Phase 3] 任务依赖图
│   ├── workspace.py         # [Phase 4] 工作区隔离
│   ├── session_state.py     # 会话状态管理
│   ├── health.py            # 三层健康检查
│   └── hot_reload.py        # 技能热更新
├── skills/
│   ├── router/              # 情境感知 + 意图识别
│   ├── commander/           # SOP 下发 + 通知
│   ├── memory_ops/          # RAG 检索 + SOP 萃取
│   ├── persona/             # 数字分身对话
│   ├── persona_extract/     # 老员工访谈萃取 (F-013)
│   ├── watcher/             # SLA 巡检 + 催办
│   └── todo/                # 任务分解
├── knowledge/
│   ├── db_client.py         # SQLite 元数据
│   ├── vector_store.py      # PostgreSQL pgvector 向量检索
│   └── db_init.py           # 建表脚本
└── tools/
    ├── llm_wrapper.py       # LLM 统一接口
    ├── wechat_client.py     # 企微消息
    ├── sms_client.py        # 短信/语音
    ├── tool_executor.py     # 工具执行器 + 权限 hook
    └── circuit_breaker.py   # 熔断器
```

---

## 旧版本地开发运行（非企业 MVP 入口）

### 前置

- Python 3.10+
- 企业微信应用（CorpID + AgentID + CorpSecret + EncodingAESKey）
- LLM API（OpenAI / 通义千问 / 智谱GLM）可选，Demo 模式可跳过

### 安装

```bash
cd memory-palace-os
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\activate  # Windows

pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入非 LLM 密钥配置

python -c "from src.memory_palace.knowledge.db_init import init_db; init_db()"
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

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

访问 `/admin/` 进入正式企业运营工作台，包含 13 个产品视图：

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

**数字分身访谈萃取流程：**

```
点击「唤醒新专家分身」→ 填写专家代号与职务 → 确认保存
    ↓ 自动弹出访谈窗口
回答 5 类结构化问题（触发情境 / 判断行为 / 经验教训等）
    ↓ 全部回答完毕
点击「结束萃取」→ 逻辑条目自动存入分身档案
    ↓
点击分身卡片 → 向该专家提问 → 获取第一人称回答
```

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
| `WECHAT_*` / `SMS_*` / `VOICE_*` | 选填 | 缺少真实供应商配置时安全禁用 |

DeepSeek API Key 不写入 EnvFile，而是通过 `scripts/set_deepseek_secret.ps1` 一次性注入外部 Docker volume。所有生成式调用固定使用 `deepseek-flash`，正式 MVP 不允许通过 `DEMO_MODE` 或 Mock 绕过模型。

---

## API 端点

### v1

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/health` | 健康检查 |
| `GET` | `/api/v1/stats` | 系统统计 |
| `GET` | `/api/v1/stats/sla` | SLA 合规率 |
| `GET` | `/api/v1/sessions` | 会话列表 |
| `POST` | `/api/v1/sessions` | 创建会话 |
| `DELETE` | `/api/v1/sessions/{id}` | 关闭会话 |
| `GET` | `/api/v1/messages/{id}` | 消息详情 |
| `GET` | `/api/v1/skills` | 注册技能列表 |
| `GET` | `/api/v1/admin/dashboard` | 仪表盘统计 |
| `GET` | `/api/v1/admin/events` | 事件记忆库列表 |
| `POST` | `/api/v1/admin/events` | 手动录入事件 |
| `GET` | `/api/v1/admin/push_logs` | 推送日志 |
| `GET` | `/api/v1/admin/personas` | 数字分身列表 |
| `POST` | `/api/v1/admin/personas` | 创建数字分身 |
| `DELETE` | `/api/v1/admin/personas/{id}` | 删除数字分身 |
| `POST` | `/api/v1/admin/personas/{id}/interview/start` | 启动访谈萃取 |
| `POST` | `/api/v1/admin/personas/{id}/interview/continue` | 继续访谈 |
| `POST` | `/api/v1/admin/personas/{id}/interview/finalize` | 完成访谈萃取 |
| `POST` | `/api/v1/admin/personas/{id}/chat` | 向分身提问 |
| `GET` | `/api/v1/admin/approvals` | 列出待审批请求 |
| `POST` | `/api/v1/admin/approvals/{id}/approve` | 批准审批 |
| `POST` | `/api/v1/admin/approvals/{id}/reject` | 拒绝审批 |

### v2

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v2/dispatch` | 直接派发消息 |
| `GET` | `/api/v2/sessions/{id}/context` | 获取会话上下文 |
| `POST` | `/api/v2/sessions/{id}/handoff` | 跨 Agent 交接 |

---

## 监控指标

```
memory_palace_requests_total{method, endpoint, status}
memory_palace_request_duration_seconds{method, endpoint}
memory_palace_messages_processed_total{agent, status}
memory_palace_llm_calls_total{provider, model}

# SLA 指标
memory_palace_sla_breach_total{priority}     # P0/P1/P2 超时次数
memory_palace_sla_response_seconds{priority}  # 实际响应时长

# 熔断指标
memory_palace_circuit_breaker_state{name, state}
memory_palace_circuit_breaker_failures_total{name}
```

健康检查：
```
GET /health/live    → Kubernetes liveness probe
GET /health/ready   → Kubernetes readiness probe
GET /health/deep    → 深度检查（数据库 + LLM 连通性）
```

---

## 测试

```bash
# 运行全部测试
pytest tests/ -v

# 只跑 P0 全链路
pytest tests/integration/test_p0_full_chain.py -v

# 只跑单元测试
pytest tests/unit/ -v
```

---

## 常见问题

**Q: 企微回调收不到消息**
- 检查外网是否可达：`curl https://your-domain.com/health`
- 确认企微后台填写的回调地址与实际一致
- 确认 AES Key 长度为 43 位（Base64）

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

## License

MIT
