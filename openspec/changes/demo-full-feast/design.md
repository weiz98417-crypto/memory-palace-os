## Context

CEO Plan `2026-07-24-demo-full-feast.md` 已通过 3 轮 spec review（7/10，Scope + Feasibility PASS）。本 design 引用其中的架构决策，聚焦实现细节。

现有基础设施：`demo_router`（gateway.py）、`_demo_results` 内存缓存、`demo_console.html`（5 标签页）、`MESSAGE_QUEUE`、`task_graph` 单例、`incident_logs`/`push_logs` 表、PersonaExtractSkill 内部 `_start_interview`/`_continue_interview`/`_finalize_persona` 方法。

## Goals / Non-Goals

**Goals:**
- 6 标签页演示控制台覆盖全部核心功能
- PersonaExtract 多轮访谈：start → continue × 4 → finalize → 展示提取条目
- Todo 任务分解：通过队列派发 → orchestrator 路由 → 结果读 TaskGraph → 渲染依赖树
- 知识库：2 场景种子数据 + 独立 ChromaDB collection + 场景热切换
- Watcher 日志：读 incident_logs + push_logs 合并展示
- Auto-play 引擎 + pipeline 动画 + 报告导出

**Non-Goals:**
- 不修改 queue_worker 核心逻辑（仅 orchestrator 加 5 行路由分支）
- 不新建数据库表
- 不改变生产路径行为
- PersonaExtract 访谈状态不持久化到 DB

## Decisions

参照 CEO Plan architecture decisions D1-D8（pipeline post-hoc replay、watcher 读现有表、todo 通过队列、persona 内存状态、独立 ChromaDB collection、await 不用 asyncio.run、专用 knowledge/search 端点、参数 reorder + question count fix）。

## Risks / Trade-offs

- [Risk] PersonaExtract 访谈状态在内存中，服务重启丢失 → 接受，demo 场景
- [Risk] 多 tab 并发访谈无锁保护 → 文档标注已知局限
- [Risk] 种子数据场景切换全量重建 ChromaDB collection → 接受，demo 数据量小
- [Risk] Frontend 1200-1600 行单文件维护 → 接受，演示工具不需要模块化拆分
