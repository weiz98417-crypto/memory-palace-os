# Memory Palace OS

景区运营智能应急响应系统。

---

## 一句话定位

当员工在企微群发"有人晕倒了"，系统 30 秒内自动完成：**识别紧急程度 → 下发处置指令 → 通知值班经理 → 记录归档**。比人快，比人全，比人不漏。

---

## 核心场景

### 场景 A：突发应急（实时）

```
员工企微群 →「B区长廊有老年游客晕倒了，呼吸微弱」
         ↓
    Gateway 接收 XML，解密，分配 trace_id
         ↓
    Router 识别 → P0 紧急 / intent=emergency_dispatch
         ↓
    Commander 下发 SOP →「1.立即拨打120 2.取AED 3.拉警戒线」
         ↓
    WeChat 推送指令给员工 + 短信/语音通知值班经理
         ↓
    SLA 记录响应时间
    IncidentLog 归档
```

### 场景 B：例行巡检（离线）

```
Scheduler 每日 20:00 定时触发
         ↓
    Watcher 扫描全量未闭环工单
         ↓
    超时 → WeChat 催办卡片 + SMS 通知
    闭环 → 萃取经验，生成 SOP 草稿
```

### 场景 C：员工对话（日常）

```
员工提问 → Router 识别为 routine
         ↓
    Memory Ops RAG 检索相似历史处置经验
         ↓
    Persona 数字分身给出个性化建议
         ↓
    结果返回企微
```

---

## 技术架构

```
企微 Webhook (AES-256-CBC)
         ↓
    Gateway ─── 签名验证 / 消息去重 / XML解析
         ↓
    Orchestrator ─── 意图分发 / SLA记录 / Agent调度
         │
         ├── Router      意图识别 & 紧急分诊
         ├── Commander   P0/P1 级 SOP 指令下发
         ├── Memory Ops  RAG 历史经验检索
         ├── Persona     数字分身对话
         └── Watcher     SLA 巡检 & 催办

工具层 ── WeChat Client / SMS Client / Voice Call / LLM Wrapper
         ↓
    ChromaDB (向量) + SQLite (元数据)
```

---

## 目录结构

```
src/memory_palace/
├── api/                        # FastAPI 路由
│   ├── v1/                     # v1 API
│   │   └── endpoints/           # admin / sessions / messages / skills
│   └── v2/                     # v2 API
├── config/                      # 配置加载 (app_settings / env_validator)
├── core/                        # 核心引擎
│   ├── orchestrator.py         # 调度器：意图路由 → Agent派发
│   ├── gateway.py              # 网关：企微回调入口
│   ├── skill_base.py          # Agent 基类 & SkillOutput
│   ├── health.py               # 三层健康检查 (live/ready/deep)
│   ├── hot_reload.py           # 技能热更新
│   ├── scheduler.py            # APScheduler 定时任务
│   ├── queue_worker.py         # 异步消息队列
│   └── session_state.py        # 会话状态管理
├── skills/                      # 5 大 Agent
│   ├── router/                 # 意图识别 & P0 关键字检测
│   ├── commander/              # SOP 下发 & 企微通知
│   ├── memory_ops/             # RAG 检索 & SOP 萃取
│   ├── persona/               # 数字分身对话
│   └── watcher/                # SLA 巡检 & 催办触发
├── knowledge/                  # 知识层
│   ├── db_client.py            # SQLite + aiosqlite 元数据
│   ├── vector_store.py         # ChromaDB 向量检索
│   ├── db_init.py              # 建表脚本
│   ├── data_seeder.py          # 种子数据导入
│   └── migrate_seed_data.py    # 数据迁移
├── tools/                      # 工具集
│   ├── llm_wrapper.py          # LLM 统一接口
│   ├── wechat_client.py        # 企微消息收发
│   ├── sms_client.py           # 短信/语音 (ThreadPool 并行)
│   ├── circuit_breaker.py      # 熔断器
│   └── rate_limiter.py         # 限流器
├── metrics/                    # 监控
│   ├── alerting.py             # 告警规则
│   └── collectors/             # 各维度指标采集
static/                         # 前端静态文件
main.py                         # FastAPI 应用入口
requirements.txt
.env.example
```

---

## 快速开始

### 前置

- Python 3.10+
- 企业微信应用（CorpID + AgentID + CorpSecret + EncodingAESKey）
- LLM API（OpenAI / 通义千问 / 智谱GLM）可选，Demo 模式可跳过

### 安装

```bash
# 1. 进入目录
cd memory-palace-os

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入企业微信参数和 LLM API Key

# 5. 初始化数据库
python -c "from src.memory_palace.knowledge.db_init import init_db; init_db()"

# 6. 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 企微回调地址（外网可达后）
https://your-domain.com/webhook/v1/callback

# 前端管理界面
http://localhost:8000/admin
# 管理员账号: admin / 123456
```

---

## Agent 矩阵

| Agent | 优先级 | 触发条件 | 核心输出 |
|---|---|---|---|
| Router | P0 | 任意消息 | intent / severity / target_agent |
| Commander | P1 | P0/P1 或 intent=emergency_dispatch | SOP 指令 + 企微推送 + SLA记录 |
| Memory Ops | P2 | routine 或显式检索 | RAG 检索结果 + SOP 草稿 |
| Persona | P3 | 多轮对话 | 个性化建议 + 经验萃取 |
| Watcher | 后台 | 定时触发 / 超时监控 | 催办卡片 + 告警通知 |

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

### 技能热更新

每个 Skill 目录下的 `config.yaml` 变更后自动生效，无需重启服务。

```yaml
# skill 内部 config.yaml 示例
rag_config:
  top_k: 5
  similarity_threshold: 0.72
  max_reference_chars: 2000
critical_keywords_boost:
  - 晕倒
  - 明火
  - 持械
  - 120
```

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

### v2

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v2/dispatch` | 直接派发消息（绕企微） |
| `GET` | `/api/v2/sessions/{id}/context` | 获取会话上下文 |
| `POST` | `/api/v2/sessions/{id}/handoff` | 跨 Agent 交接 |

---

## 监控指标

通过 `/metrics` 端点暴露（Prometheus 格式）：

```
# 核心指标
memory_palace_requests_total{method, endpoint, status}
memory_palace_request_duration_seconds{method, endpoint}
memory_palace_messages_processed_total{agent, status}
memory_palace_llm_calls_total{provider, model}
memory_palace_llm_latency_seconds{provider}

# SLA 指标
memory_palace_sla_breach_total{priority}  # P0/P1/P2 超时次数
memory_palace_sla_response_seconds{priority}  # P0/P1 实际响应时长

# 熔断指标
memory_palace_circuit_breaker_state{name, state}
memory_palace_circuit_breaker_failures_total{name}
```

健康检查端点：

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
