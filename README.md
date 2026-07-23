# Memory Palace OS

**景区运营智能应急响应与经验传承系统**

基于 OpenClaw 多Agent架构启发，融合 Harness 式自主Agent生命周期管理，打造景区运营场景下的**智能体协作平台**。

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
| **Router** | 情境感知 · 意图识别 · P0 关键字检测 | 所有消息 |
| **Commander** | SOP 指令下发 · 企微/短信/语音通知 | P0/P1 事件 |
| **Memory Ops** | RAG 经验检索 · SOP 草稿萃取 | routine 检索 |
| **Persona** | 数字分身对话 · 访谈萃取 · 个性化建议生成 | 多轮对话 |
| **PersonaExtract** | 老员工结构化访谈萃取 · 逻辑条目提取 | 管理后台 / 访谈 API |
| **Watcher** | SLA 巡检 · 催办触发 · 异常预警 | 定时任务 |
| **TodoWrite** | 复杂目标 → 任务依赖图分解 | Agent 调用 |

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

```
企微 Webhook (AES-256-CBC)
         ↓
    Gateway ─── 签名验证 / 消息去重 / XML解析
         ↓
    Orchestrator ─── 意图分发 / SLA 记录 / Agent 调度
         │
         ├── Router          意图识别 & P0 紧急分诊
         ├── Commander        P0/P1 SOP 指令下发
         ├── Memory Ops       RAG 历史经验检索
         ├── Persona          数字分身对话
         ├── Watcher          SLA 巡检 & 催办
         └── TodoWrite        任务分解 (Phase 3)
         │
         ▼
    [Phase 1] 三层上下文压缩 ── Hot/Warm/Cold tiering
         │
         ▼
    [Phase 2] 权限引擎 ── Level 0/1/2 + 审批流
         │
         ▼
    [Phase 3] 任务依赖图 ── 持久化 & Docker 重启恢复
         │
         ▼
    [Phase 4] 工作区隔离 ── chroot + 路径遍历防护

工具层 ── WeChat / SMS / Voice Call / LLM Wrapper / Tool Executor
         ↓
    ChromaDB (向量) + SQLite (元数据)
```

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
│   ├── vector_store.py      # ChromaDB 向量检索
│   └── db_init.py           # 建表脚本
└── tools/
    ├── llm_wrapper.py       # LLM 统一接口
    ├── wechat_client.py     # 企微消息
    ├── sms_client.py        # 短信/语音
    ├── tool_executor.py     # 工具执行器 + 权限 hook
    └── circuit_breaker.py   # 熔断器
```

---

## 快速开始

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
# 编辑 .env 填入企业微信参数和 LLM API Key

python -c "from src.memory_palace.knowledge.db_init import init_db; init_db()"
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 验证

```bash
curl http://localhost:8000/health
# 健康检查返回 {"status": "ok"}

# 企微回调地址（外网可达后）
https://your-domain.com/webhook/v1/callback

# 前端管理界面
http://localhost:8000/admin
# 管理员账号: admin / 123456

### 管理后台功能

访问 `/admin` 进入管理控制台，包含以下模块：

| 模块 | 说明 |
|------|------|
| **记忆卷宗** | 事件列表 · 事件详情 · 手动录入 |
| **数字分身** | 分身列表 · 创建分身 · 访谈萃取 · 向分身提问 |
| **推送日志** | 推送采纳率统计 · 推送记录查询 |
| **仪表盘** | 记忆库总量 · 本周新增 · 采纳率 · 事件分布 |

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
```

---

## 配置说明

### .env 核心变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `WECOM_CORP_ID` | ✅ | 企业 ID |
| `WECOM_AGENT_ID` | ✅ | 应用 AgentId |
| `WECOM_CORP_SECRET` | ✅ | 应用密钥 |
| `WECOM_ENCODING_AES_KEY` | ✅ | 回调 AES Key（43位） |
| `WECOM_TOKEN` | ✅ | 回调 Token |
| `LLM_PROVIDER` | 选填 | `openai` / `qwen` / `zhipu`，默认 openai |
| `LLM_API_KEY` | 选填 | API Key |
| `LLM_MODEL` | 选填 | 模型名，默认 gpt-4 |
| `DEMO_MODE` | 选填 | `true` 时跳过 LLM 调用，使用 Mock 响应 |

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
- 检查 `.env` 是否存在且变量完整
- 检查数据库目录权限：`chmod 755 data/`

**Q: LLM 调用失败**
- 设置 `DEMO_MODE=true` 跳过 LLM，使用 Mock 响应
- 检查 API Key 是否正确，网络是否可达

---

## License

MIT
