## Context

当前 `static/admin_frontend.html` 是已有的管理大屏（消息列表、统计数据），但它是单向查看工具，不适合交互式演示。演示需要"发消息→看 pipeline 实时执行→看回复"的闭环体验。

已有基础设施：
- `POST /demo/send` + `GET /demo/result/{trace_id}`：消息发送+结果轮询，链路已验证
- `GET /v1/knowledge/query`：知识库向量检索
- `GET /v1/admin/stats`：系统统计
- `GET /v1/skills`：技能列表
- `/admin` StaticFiles 挂载：已有文件可被浏览器直接访问

约束：
- 纯前端方案，不引入 npm/webpack/框架
- 所有 API 端点已在 demo_router 或 v1_router 中
- 演示控制台挂载在已存在的 `/admin` 路径下

## Goals / Non-Goals

**Goals:**
- 提供一个多标签页演示控制台，覆盖 5 个核心功能域：消息链路、任务系统、知识库、系统监控、管理后台
- 展示 pipeline 执行过程（ContextTrigger → Router → Agent），而非仅展示最终回复
- 控制台页面布局简洁专业，适合投影演示
- 辅以命令行演示脚本，供不需要 UI 的场景使用

**Non-Goals:**
- 不是生产功能，不加认证/权限
- 不改造已有管理大屏（`admin_frontend.html`），控制台是新增的独立页面
- 不修改 skill 内部逻辑或 orchestrator 路由
- 不做 WebSocket 实时推送（用轮询即可）

## Decisions

**D1: 单 HTML 文件 vs 多文件前端应用**
选择单 HTML 文件。演示控制台约 500 行（含内联 CSS/JS），无需构建工具。挂载在已有 StaticFiles 下即可访问。不需要 npm/webpack/vite。

**D2: 数据获取方式 — 轮询 vs WebSocket**
选择轮询。`GET /demo/result/{trace_id}` 每 1 秒轮询一次，最多 15 次。实现简单，对演示场景完全够用（消息处理约 3-8 秒）。

**D3: 5 个标签页 vs 单页滚动**
选择标签页。每个标签页展示一个功能域，观众可以清楚看到系统的能力边界。单页滚动会让不同功能混在一起，演示时难以导航。

**D4: Pipeline 可视化方式**
用简单的 HTML/CSS 横向流程图表示 ContextTrigger → Router → Agent。每个节点用颜色标记状态（灰色=待执行，蓝色=执行中，绿色=完成，红色=异常）。不做 SVG/Canvas 图形库。

**D5: 新增后端端点**
在 `gateway.py` 的 `demo_router` 中新增 2 个端点：
- `GET /demo/stats`：聚合 stats，返回 `{queue_depth, message_count, task_count, last_watcher_run, skills_registered}`
- `GET /demo/tasks`：返回 TaskGraph 中所有任务的列表（id、description、status、dependencies、assigned_agent）

这两个端点复用已有的 `db_client` 和 `task_graph` 查询，不引入新依赖。

## Risks / Trade-offs

- [Risk] `GET /demo/tasks` 读的是内存中的 TaskGraph，服务重启后任务数据来自数据库恢复 → 影响小，演示时任务量很少
- [Risk] 轮询可能偶尔超时（LLM 调用慢时）→ 设置 15 次 × 1s 的轮询上限，超时后提示用户手动刷新
- [Risk] 控制台只在 DEMO_MODE 下可用 → 符合设计意图
