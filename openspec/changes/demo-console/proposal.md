## Why

当前 `DEMO_MODE=true` 下的 `/demo/send` + `/demo/result` 已能跑通单条消息的完整链路，但只暴露了"发消息→收回复"这一种交互。项目的 8 个 skill（ContextTrigger、Router、Commander、Persona、PersonaExtract、MemoryOps、Todo/TaskGraph、Watcher）中有一半根本没有演示入口。演示时需要 curl 命令行 + 手动拼接 JSON，对非技术观众不友好。在接洽合作方或投资人前，需要一个统一的、可视化的演示控制台，覆盖全部核心功能。

## What Changes

- 新增 `static/demo_console.html`：多标签页 Web 演示控制台，纯前端，通过已有 `/demo/send`、`/demo/result`、`/v1/knowledge/query` 等 API 驱动
- 新增 `GET /demo/stats` 端点：返回系统运行统计（队列深度、消息数、任务数、巡检状态），供控制台仪表盘使用
- 新增 `GET /demo/tasks` 端点：返回 TaskGraph 中当前的任务列表和依赖关系，供任务系统标签页展示
- 新增 `scripts/demo.sh`：命令行演示脚本，按分幕剧本自动发送预设消息并轮询结果
- demo 控制台通过已有的 `/admin` StaticFiles 挂载自动可用，无需新增路由

## Capabilities

### New Capabilities
- `demo-console`: 多标签页 Web 控制台，覆盖消息链路演示、任务系统可视化、知识库检索、系统状态监控
- `demo-stats`: 后端统计端点，聚合消息数、任务数、队列状态、巡检信息
- `demo-tasks`: TaskGraph 任务列表端点，返回任务节点和依赖边供前端渲染

### Modified Capabilities
- `<none>`

## Impact

- 新增文件：`static/demo_console.html`（~500 行）、`scripts/demo.sh`（~60 行）
- 修改文件：`src/memory_palace/core/gateway.py`（demo_router 新增 3 个端点，~60 行）
- 无需新增依赖，无需改数据库 schema
- 不影响生产路径（均在 `DEMO_MODE=true` 或 `/demo` 前缀下）
