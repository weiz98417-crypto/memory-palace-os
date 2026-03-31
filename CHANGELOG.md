# 变更说明 (CHANGELOG)

## 2026-03-30 追加修复

### 4. 前端 / API 集成修复
**问题汇总**: `main.py` 未注册 v1/v2 路由，导致 `/api/v1/*` 接口全部 404；前端 `static/index.html` API 路径错误；`admin.py`/`sessions.py`/`messages.py` 从 `knowledge` 导入 `db_client` 实例而非模块级 async 函数。

**修复清单**:
- `main.py`: 添加 `from src.memory_palace.api import v1_router, v2_router` 并 `app.include_router` 注册
- `static/index.html`: API_BASE 从 `/v1` 修正为 `/api/v1`；移除错误的 `{code:0,data}` 包装解析；健康检查改为 `/api/v1/admin/health`
- `api/v1/endpoints/admin.py`: 导入改为 `from ...knowledge.db_client import check_connection, get_stats`；新增 `/admin/queue` 端点；添加 `PlainTextResponse` import
- `api/v1/endpoints/sessions.py`: 同上改为直接导入 `get_sessions`/`get_session_by_id`；修复 `SessionStateManager.close_session` 调用方式（需实例化 + await）
- `api/v1/endpoints/messages.py`: 同上改为直接导入 `get_message`
- `api/v1/schemas.py`: `SessionInfo` schema 字段与 sessions 表对齐（`active_agent`/`created_at:float`/`stage` 等）
- `core/health.py`: `db_client.check_connection()` 改为 `from ...db_client import check_connection`
- `api/v1/endpoints/skills.py`: 技能列表从 `config.yaml` 的 `agent_metadata` 读取 description/version

### 5. memory_ops 缺少 config.yaml
**文件**: `src/memory_palace/skills/memory_ops/config.yaml`

**问题**: `memory_ops/skill.py` 第 52 行从 `config.yaml` 加载 `agent_name`/`llm_config`/`rag_config`，但该文件不存在（其他 4 个 skill 均已有）。skill 有兜底默认值，但正式环境应提供完整配置。

**修复**: 新增 `memory_ops/config.yaml`，包含 `agent_metadata`（name/version/description）、`llm_config`（model/temperature/top_p/max_tokens/json_mode/timeout）、`rag_config`（top_k/similarity_threshold/max_reference_chars）、`logic_controls` 和 `observability` 四个标准配置段。

### 1. knowledge 层导入路径修复
**文件**: `src/memory_palace/knowledge/migrate_seed_data.py`, `data_seeder.py`

**问题**: 使用 `from memory_palace.knowledge.db_client`（错误路径），且 `IncidentLog` 和 `SOPDocument` 在 `tools.db_client` 而非 `knowledge.db_client`。

**修复**: 导入路径改为 `from src.memory_palace.tools.db_client import db_manager, IncidentLog, SOPDocument`

### 2. SOPDocument ORM 模型缺失
**文件**: `src/memory_palace/tools/db_client.py`

**问题**: `data_seeder.py` 使用 SQLAlchemy ORM 模型 `SOPDocument`，但该类从未定义。

**修复**: 在 `tools/db_client.py` 中添加完整的 `SOPDocument` ORM 模型（`__tablename__ = 'sop_documents'`，字段：id, category, title, content, priority, version, updated_at）。

### 3. migrate_seed_data.py 字段映射错误
**文件**: `src/memory_palace/knowledge/migrate_seed_data.py`

**问题**: `IncidentLog` 构造参数与 ORM 模型字段名不匹配（用 `raw_query`/`ai_instruction` 而 ORM 模型只有 `dispatched_instruction`）。

**修复**: 对齐 `IncidentLog` 构造参数：`case_id`, `severity`, `dispatched_instruction`, `employee_replies`, `is_resolved`, `audit_status`。

---

## 本次重建 - 修复与新增

本次更新从"项目代码包"重建为完整的 `memory-palace-os` 可运行代码包，修复了所有已识别问题。

---

## P0 关键修复

### 1. 缺失 wechat_crypto.py 企微加解密模块
**问题**: `gateway.py` 导入了 `from memory_palace.utils.wechat_crypto import WXBizMsgCrypt`，但文件不存在。

**修复**: 创建 `src/memory_palace/tools/wechat_crypto.py`，实现完整的 AES-256-CBC 加解密：
- `WXBizMsgCrypt` 类：官方企微 AES 加解密规范实现
- `MockWeChatCrypto`：开发模式 Mock
- `create_wechat_crypto()` 工厂函数：自动降级

### 2. orchestrator.py 调用错误方法
**问题**: `orchestrator.py` 调用 `skill.execute(context)`，但 `BaseAgentSkill` 的正确入口方法是 `run()`。

**修复**: 将 `skill.execute(context)` → `await skill.run(context)`

### 3. scheduler.py 导入路径与方法调用错误
**问题**:
- 导入路径 `memory_palace.skills.watcher.skill` 不存在
- `watcher.run()` 是异步方法但未 `await`
- `result.structured_data` 属性不存在

**修复**:
- 导入路径改为 `from ...skills.watcher import WatcherSkill`
- 使用 `asyncio.run()` 包装异步调用
- 修复属性访问为 `result.get('processed_count', ...)`

### 4. gateway.py 企微类名错误
**问题**: 导入 `WeChatCrypto` 但实际类名是 `WXBizMsgCrypt`。

**修复**: `from src.memory_palace.tools.wechat_crypto import WXBizMsgCrypt`

### 5. gateway.py 数据库调用未 await
**问题**: `db_client.check_connection()` 等方法改为 async 函数后，gateway.py 未加 `await`。

**修复**: 所有 db_client 方法调用前加 `await`，并从 `src.memory_palace.knowledge.db_client` 导入对应异步函数。

---

## P1 新增模块

### 6. 技能注册中心 (skill registration)
**文件**: `src/memory_palace/skills/__init__.py`
- `@register_skill` 装饰器
- `get_skill_by_name()` 按名查找
- `get_registered_skills()` 获取所有技能
- `reload_skill()` 热重载

### 7. metrics/collectors 指标收集层
**目录**: `src/memory_palace/metrics/collectors/`
- `request_metrics.py` — HTTP 请求计数器、延迟直方图
- `token_metrics.py` — LLM Token 消耗、费用统计
- `queue_metrics.py` — 队列深度、处理速率
- `agent_metrics.py` — Agent 请求计数、交接追踪
- `system_metrics.py` — CPU、内存、线程、DB 连接

### 8. metrics/alerting.py 告警规则
**文件**: `src/memory_palace/metrics/alerting.py`
- P0~P4 分级告警定义（15个告警规则）
- `AlertingManager` 告警管理器
- `send_alert()` / `resolve_alert()` 快捷函数

### 9. metrics/dashboards/ Grafana 面板
- `api_dashboard.json` — API QPS、延迟、错误率
- `agent_dashboard.json` — Agent 请求量、Token 消耗
- `system_dashboard.json` — CPU、内存、队列监控

### 10. api/v1/ 完整 REST API 层
**目录**: `src/memory_palace/api/v1/`
- `router.py` — 路由聚合
- `schemas.py` — Pydantic 请求/响应模型
- `endpoints/messages.py` — 消息接口
- `endpoints/skills.py` — 技能接口 + 热重载
- `endpoints/sessions.py` — 会话管理
- `endpoints/admin.py` — 健康检查、统计、配置重载

### 11. api/v2/ API v2 框架
- `router.py` — v2 路由聚合
- `schemas.py` — v2 请求模型（支持优先级、批量消息）

### 12. knowledge/db_client.py 异步方法补全
新增模块级异步函数：
- `check_connection()` — 连接检查
- `get_message(message_id)` / `get_message_by_id(msg_id)`
- `get_messages(session_id)` / `get_messages_by_session(session_id)`
- `get_sessions(user_id, limit)` / `get_session_by_id(session_id)`
- `save_message(payload)` — 保存消息
- `create_or_update_session(user_id)` — 创建/更新会话
- `update_sla_response(msg_id)` — 更新 SLA 响应时间
- `delete_session(session_id)` — 删除会话
- `get_stats()` — 系统统计

同时修复 `self._path` → `self.db_path` 拼写错误。

### 13. static/admin_frontend.html 管理后台
- 完整 SaaS 管理大屏（组件状态、统计卡片、技能管理、会话列表）
- 实时刷新 + API 集成

---

## P2 配置文件

### 14. 配置与环境
- `.env.example` — 所有环境变量模板（含企微、LLM、Redis、监控）
- `requirements.txt` — 完整依赖列表（所有包版本约束）
- `.gitignore` — Python 项目标准忽略规则
- `LICENSE` — MIT License
- `run.sh` — 一键启动脚本

### 15. Grafana Provisioning
- `deploy/grafana/provisioning/datasources/datasource.yml` — Prometheus 数据源
- `deploy/grafana/provisioning/dashboards/dashboard.yml` — Dashboard 配置
- `deploy/grafana/provisioning/dashboards/agent_overview.json` — Agent 全景面板

---

## 架构确认（无需修改）

以下文件从原始"项目代码包"复制，结构正确无需修改：

| 文件 | 说明 |
|------|------|
| `core/skill_base.py` | BaseAgentSkill 抽象基类，`run()` 是正确的模板方法入口 |
| `skills/*/skill.py` | 所有 5 个 Skill 文件已有正确的 3-dot 相对导入 |
| `tools/llm_wrapper.py` | async LLM 客户端，实现正确 |
| `tools/circuit_breaker.py` | 熔断器实现正确 |
| `knowledge/vector_store.py` | ChromaDB 封装正确 |
| `knowledge/db_init.py` | 数据库初始化正确 |
| `core/hot_reload.py` | 热重载实现正确 |
| `config/app_settings.py` | Pydantic Settings 配置正确 |

---

## 目录结构对比

### 重建前（缺失）
```
metrics/collectors/    ❌ 缺失
api/v1/                ❌ 缺失
api/v2/                ❌ 缺失
tools/wechat_crypto.py ❌ 缺失
static/admin_frontend  ❌ 缺失（目录存在但为空）
```

### 重建后（完整）
```
metrics/
  ├── collectors/
  │   ├── __init__.py ✅
  │   ├── request_metrics.py ✅
  │   ├── token_metrics.py ✅
  │   ├── queue_metrics.py ✅
  │   ├── agent_metrics.py ✅
  │   └── system_metrics.py ✅
  ├── alerting.py ✅
  └── dashboards/
      ├── api_dashboard.json ✅
      ├── agent_dashboard.json ✅
      └── system_dashboard.json ✅
api/
  ├── v1/
  │   ├── __init__.py ✅
  │   ├── router.py ✅
  │   ├── schemas.py ✅
  │   └── endpoints/
  │       ├── __init__.py ✅
  │       ├── messages.py ✅
  │       ├── skills.py ✅
  │       ├── sessions.py ✅
  │       └── admin.py ✅
  └── v2/
      ├── __init__.py ✅
      ├── router.py ✅
      └── schemas.py ✅
tools/
  └── wechat_crypto.py ✅ (P0 关键修复)
static/
  └── admin_frontend.html ✅
deploy/grafana/provisioning/ ✅
.env.example ✅
requirements.txt ✅
.gitignore ✅
LICENSE ✅
run.sh ✅
CHANGELOG.md ✅
```
