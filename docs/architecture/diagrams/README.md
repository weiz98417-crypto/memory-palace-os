# Memory Palace OS 架构图集

[打开上一级的离线图集首页](../index.html)。每张图都有可直接打开的独立 HTML，以及同名可编辑 JSON。

| 图 | 阅读重点 | 源码入口 |
| --- | --- | --- |
| [01 系统全景](01-system-overview.architecture.html) | 四个前端、共享 API/数据库/Redis、消息与建议两条 Stream、模型与嵌入 | `main.py`、`deploy/docker-compose.yml` |
| [02 建议运行](02-advice-runtime.architecture.html) | `scenic_commands`、派发模式、租约、恢复与 SSE | `scenic/advice_runs.py`、`scenic/advice_dispatch.py` |
| [03 事件七状态](03-incident-lifecycle.workflow.html) | `DETECTED` 到 `CLOSED`，区分处置完成与关闭 | `scenic/operations.py` |
| [04 消息接报时序](04-message-ingress.sequence.html) | 鉴权、统一接报、幂等、入队与 202 响应 | `core/canonical_ingress.py`、`api/v1/endpoints/messages.py` |
| [05 Agent 主干](05-agent-trunk.workflow.html) | ContextTrigger、Router、MemoryOps、Commander 模式分支与降级 | `incident/command.py` |
| [06 知识双路径](06-knowledge-paths.architecture.html) | 已发布来源索引、同模型嵌入、查询时核验与检索快照 | `knowledge/evidence_backed_retrieval.py`、`knowledge/vector_schema.py` |
| [07 Compose 部署](07-deployment.architecture.html) | 默认服务、网络、可选 profiles 与 Hatchet 显式切换 | `deploy/docker-compose.yml` |
| [08 经验治理](08-experience-governance.workflow.html) | 来源、确权、驳回、发布、废弃、授权使用 | `core/experience_assets.py`、`knowledge/experience_schema.py` |
| [09 前端与 API](09-frontend-api.architecture.html) | 四个 Vue 应用、共享入口、四组 API 业务域 | `frontend/apps/console/src/router.ts`、`api/v1/router.py` |
| [10 关闭门禁](10-resolution-gate.architecture.html) | 任务、审批、图片、SOP、告警五条件与单独关闭动作 | `scenic/operations.py` |
| [11 恢复与巡检](11-recovery-watcher.architecture.html) | 启动恢复、巡检调度、策略、运行与发现 | `core/runtime_recovery.py`、`core/scheduler.py` |
| [12 演示边界](12-demo-boundary.architecture.html) | `DEMO_MODE` 的互斥进程分支、YAML 场景与确定性 Adapter | `main.py`、`demo/catalog.py`、`demo/adapters.py` |
| [13 景区命令](13-scenic-command.architecture.html) | 执行者、命令账本、领域事实与实时视图 | `scenic/operations.py`、`scenic/realtime.py` |
| [14 权限任务](14-permission-task.architecture.html) | 分级审批、批准后的执行结果、TaskGraph 与活动日志 | `core/permissions.py`、`core/task_graph.py` |
| [15 消息 Worker](15-message-worker.workflow.html) | 结果保存、交付、普通重试、死信及策略失败 | `core/queue_worker.py` |
| [16 可观测性](16-observability.architecture.html) | 调用账本、健康与指标、Console 诊断、可选 OTel/Jaeger | `incident/telemetry.py`、`main.py`、`api/v1/endpoints/management.py` |
| [17 消息处理与轮询](17-message-result.sequence.html) | Worker 保存结果、交付，以及客户端主动轮询终态 | `core/queue_worker.py`、`api/v1/endpoints/messages.py` |

## 事实边界

- 两条正式异步路径共用 FastAPI、PostgreSQL 和**同一 Redis 服务**，但分别使用 `memory_palace:messages` 与 `memory_palace:advice_runs` Stream。
- `POST /api/v1/messages/` 直接创建 `message_runs` 并入队；助手与企微模拟器使用 `CanonicalMessageIngress`。消息状态由客户端轮询；景区态势和建议活动另有 SSE。
- AdviceRun 存在 `scenic_commands`，类型为 `GENERATE_ADVICE`。Compose 默认 `ADVICE_EXECUTION_MODE=redis`；Hatchet 必须显式切换并准备对应 profile 与依赖。
- `READY` 表示建议运行结束，可包含 `DEGRADED` 结果；不代表建议被人采纳，也不代表依据可靠。
- `MITIGATING → RESOLVED` 的五项条件与 `RESOLVED → CLOSED` 是两道门禁。当前关闭案例向量与处置结论含固定演示场景文案。
- `DEMO_MODE=true` 跳过正式 lifespan，且不挂载正式 v1/v2/webhook 路由。演示 Adapter 的回执不是外部渠道送达。
- 无文字的边仅表示两个端点在已标明方向上通信；图中的并列节点不表示调用顺序。条件分支以相应图的说明卡和源码为准。

本图集依据当前本地源码绘制；不引用未推送的 GitHub 修订号。技术校验只能检查图形和 HTML，业务事实以源码为准。
