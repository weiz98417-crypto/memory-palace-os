# 实施任务

> **Status: superseded (历史快照)** — 本变更记录当时使用的向量后端描述已被 ADR-0007（PostgreSQL pgvector 为唯一向量后端）取代，不再代表当前实现。


## M0 基础契约

- [x] 将现有 PostgreSQL 镜像切换为明确支持 pgvector 的固定版本并启用扩展。
- [x] 建立 1024 维向量列、租户过滤、索引版本和启动/索引校验。
- [x] 下载并挂载本地 bge-m3，补充 CPU/GPU 启动检查（本机只验证了 CPU 路径；GPU 为可选分支，未在本机复验）。
- [x] 定义监测信号、态势告警、运营事件和模拟时钟的正式数据模型。

## M1 景区态势垂直切片

- [x] 实现天气、设备、客流 Adapter 和可复现故事输入。
- [x] 实现人工注入、规则告警、事件转换和模拟时钟控制。
- [x] 实现 SSE 态势订阅、序号、重连和短轮询兜底。
- [x] 实现四区域离线景区作业地图和 GIS 可选连接器状态。

## M2 事件处置闭环

- [~] 将告警接入正式事件、SOP、任务、审批和通知流程（按自研规则路径实现并已验证；按 ADR-0018 的 Agent 主干标准尚未成立，见 M4）。
- [x] 实现现场端接单、回执、附件、依赖和事件关闭门禁。
- [x] 实现内部系统接入环境 outbox、送达、接单和回执。
- [x] 实现指挥中心、现场端和管理端共享状态。

## M3 体验与证据

- [x] 隐藏业务界面的模拟控制，建立受保护运行准备入口。
- [x] 预置角色账号（`simulation-ops` / `wangfang` / `liming` / `chenyu` / `knowledge-owner`）与真实角色权限。
- [x] 多角色演示启动器（只打开并按角色登录各入口窗口，业务动作全部由人工完成，不是播放脚本）+ 演示流程文档 `docs/operations/scenic-demo-runbook.md`。
- [x] 真实来源知识导入：AnySearch 采集 36 个主题、216 条结果（100 条去重可用来源），经正式 SOP 发布链路导入 42 条 SOP，并经 `POST /admin/knowledge/import` 批量导入 100 条知识条目；原始来源存证于 `artifacts/knowledge/anysearch-raw.json`。
- [x] 退役 ChromaDB：不迁移、不留依赖、不保留影子后端。
- [x] 增加垂直切片、权限、断线、重启、幂等和失败恢复测试。
- [x] 生成连续旅程证据包并更新能力状态与文档。

## M4 Agent 主干化（2026-09-16 新增）

依据 ADR-0018 与 ADR-0019，把景区处置链从自研规则路径改为 Agent 驱动。规格见 `.scratch/scenic-agent-trunk/spec.md`；决策地图与票见 `.scratch/scenic-agent-trunk/map.md` 与 `issues/01..12`。

- [x] M4-1 模型服务化：TEI 承载 bge-m3（1024 维）与 bge-reranker-base，应用去除内嵌 torch（m4-01）
- [x] M4-2 `IncidentCommand` 边界与调用记录：复用 `llm_call_logs`，字段对齐 OTel GenAI（m4-02）
- [x] M4-3 四 agent 接入：context_trigger → router → memory_ops → commander，经 LiteLLM 调同一模型（m4-02：真实 deepseek-flash、真实调用记录）
- [x] M4-4 异步建议：队列 + 状态机 + SSE，人在环采纳/忽略（m4-03：CAS 状态机、迟到结果只读保留、SSE 三类事件）
- [x] M4-5 编排与人工中断：Hatchet 承载持久化与审批中断（m4-04：正式 worker + durable event wait + dispatcher seam）
- [x] M4-6 引导与呈现：快照返回 `next_actions`/`advice`，前端渲染"分析中"与「查看处置建议」（m4-03 已接入生产建议生成器）
- [x] M4-7 可观测与诊断：Jaeger 追踪 + 诊断页展示模型与配额状态（m4-10）
- [x] M4-8 验收基线：spec delta + DeepEval 黄金样本 + 真实模型冒烟（m4-05：live 门禁评测真实主干输出 3/3）
- [x] M4-9 文档与配置同步：README、架构图、产品页、CONTEXT 术语（m4-11）
- [x] M4-10 依赖与一致性核实：pydantic-ai/Hatchet 版本兼容、TEI 与 pgvector 的 1024 维一致性（m4-12 / ADR-0020）

> M0–M3 记录"自研规则路径"的景区闭环（已完成并验证）；M4 记录"Agent 主干化"的生产落地（已全部完成：四 agent 经 LiteLLM 调真实模型、调用记录入卷宗、建议异步与人工门禁、Hatchet 持久化与人工中断、Jaeger 轨迹与 DeepEval live 门禁）。

## 剩余验证

- **Chroma 已直接舍弃**：迁移脚本、合成旧库夹具和迁移证据全部移出产品代码，隔离在 `artifacts/scenic-e2e/dropped-chroma/`（可恢复，不属于交付物）。`requirements.txt`、`pyproject.toml`、`deploy/*`、`main.py`、`src/`、`scripts/` 均无 Chroma 引用，`tests/unit/test_no_chroma_dependency.py` 守护该约束；产品页文案也从 ChromaDB 改为 PostgreSQL pgvector。客户历史旧库不在本项目范围内（ADR-0007）。
- **pgvector 数据契约**：见 `docs/vector-data-contract.md`。必需数据只有三类，全部来自正式事实表——已发布 `sop_documents`（`source_type=SOP`）、已发布经验卡、关闭事件生成的 CASE 记忆；不允许合成语料或占位向量。`scripts/verify_vector_data.py` 校验索引版本、维度、每场地各类数量，以及“每条已发布 SOP 是否都有向量”，本机原生栈与容器栈均通过。
- **Docker 复验已完成（2026-09-16）**：`docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml up -d --build` 起 pgvector/PostgreSQL 15 + Redis 7.2.5 + app(gunicorn+uvicorn worker) + nginx，四个服务 healthy；`scripts/scenic_e2e_journey.py` 经 nginx（宿主 8090 → 容器 80 → app 8000）跑完整条故事：事件 `7f8aa345-d4ca-5a0a-a9ea-21f3cecc2503` CLOSED、卷宗就绪、2 任务 DONE、2 告警 RECOVERED、审批 APPROVED/SUCCEEDED、2 条接入环境回执、SOP 命中 `postgresql_pgvector` 1024 维 score 0.7199。证据：`artifacts/scenic-e2e/docker-journey-evidence.json`、`docker-journey-database-evidence.json`、`docker-compose-ps.txt`。
- **容器化路径修复**：`SCENIC_PREP_ALLOWED_HOSTS` 之前没有任何部署入口，nginx 后面的应用永远进不了受保护运行准备入口；同时代理头未生效导致审计与门禁看到的是入口 IP。现在 `deploy/docker-compose.yml` 传递 `TRUST_PROXY_HEADERS`（默认 true）与 `SCENIC_PREP_ALLOWED_HOSTS`，`main.py` 仅在显式开启时挂载 `ProxyHeadersMiddleware`，并有 `tests/integration/test_proxy_header_trust.py` 守护“默认不信任、显式才信任”。
- **本机 Docker Desktop 前置处理**：Docker Desktop 4.88 启动时因残留 AF_UNIX socket（`%LOCALAPPDATA%\Docker\run\sailor-ingest.sock`、`%LOCALAPPDATA%\docker-secrets-engine\engine.sock`）失败。处理方式：把这两个目录改名为 `.stale-<时间戳>`（可恢复），并在 `%APPDATA%\Docker\settings-store.json` 关闭 Docker AI（`EnableDockerAI=false`，原文件已备份为 `settings-store.json.bak-*`）。这是本机环境处置，不改变仓库交付物；再次启动 Docker Desktop 前如遇同样报错，重复清理这两个目录即可。
- **2026-09-16 修复的其他真实缺陷**：CPU torch 满线程做 embedding 会原生崩溃（`EMBEDDING_CPU_THREADS` 默认 4）；高风险车辆决策被冷却拒绝会留下阻塞关闭的孤儿任务（派单前检查冷却 + 失败回滚）；SOP 检索被历史 CASE 挤占（向量接口新增 `source_types`，景区检索固定取 SOP）；子进程测试在 GBK 控制台解码中文输出会抛 `UnicodeDecodeError`（4 个测试文件显式使用 UTF-8），这是之前全量偶发失败的根因。
- 2026-09-16 全量回归 `691 passed / 0 failed / 0 skipped`（228s，`artifacts/scenic-e2e/pytest-report.json-final.xml`）；含景区状态机、HTTP 垂直故事、审批门禁、并发幂等、向量失败恢复、SSE 重连、容器化运行准备入口。
- **演示端口已统一为 8090**：compose 默认值、`.env.example`、README 与本机启动器全部对齐（旧值 8080/8082 已不再使用）。
- **知识导入的一份真实来源**：本次导入的是 AnySearch 检索到的公开标准、政府通知与行业规范，逐条保留链接；**不是客户内部制度文本**。正式交付前需客户按自身制度复核，或提供内部 SOP 后按同一链路替换。
- **仍未完成**：① 客户内部 SOP/知识原文（当前为公开来源整理稿 + 产品预置 SOP + 真实事件 CASE）；② AnySearch API Key 尚未配置到 `ANYSEARCH_API_KEY`（MCP 已注册，匿名可用但配额较低）。
