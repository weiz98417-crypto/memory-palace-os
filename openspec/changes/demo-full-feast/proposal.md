## Why

当前 `demo_console.html` 只覆盖消息链路（ContextTrigger → Router → Agent），项目的 PersonaExtract 多轮访谈、Todo 任务分解、知识库向量检索、Watcher 巡检日志等功能没有演示入口。演示时无法展示系统全貌。需要将演示控制台升级为覆盖全部核心功能的完整演示体验。

## What Changes

- 新增 5 个后端 demo 端点：PersonaExtract 访谈管理（start/continue/finalize）、Todo 任务分解、知识库搜索、巡检日志查询、场景切换
- 重构 `demo_console.html`：从 5 标签页扩展到 6 标签页，新增 PersonaExtract 访谈 UI、任务依赖树渲染、场景切换联动、pipeline 动画、auto-play 引擎、报告导出
- 新增 `scripts/seed_data/` 种子数据系统：2 个场景（日常运营 + 突发事件）的 YAML Schema，含知识库条目、老员工档案、任务目标、预设消息
- `PersonaExtractSkill` 新增 3 个 public wrapper 方法
- `Orchestrator._route()` 新增 demo_todo_decompose 消息类型路由

## Capabilities

### New Capabilities
- `persona-interview-demo`: PersonaExtract 多轮访谈的 demo API（start/continue/finalize）和前端交互 UI
- `todo-decompose-demo`: Todo 任务分解的 demo API（通过队列派发触发）和依赖图渲染
- `knowledge-seed-data`: 2 场景种子数据系统（YAML + ChromaDB + SQLite），含场景切换端点
- `watcher-log-demo`: Watcher 巡检日志查询端点，读现有 incident_logs/push_logs 表
- `demo-auto-play`: 控制台自动演示引擎，预设时间线，零操作演示
- `demo-pipeline-animation`: Pipeline 后置动画回放（post-hoc replay）
- `demo-report-export`: 演示会话报告导出（window.print + @media print CSS）

### Modified Capabilities
- `<none>`

## Impact

- 修改文件：`gateway.py`（+250 行）、`orchestrator.py`（+5 行）、`skill.py` PersonaExtract（+30 行）
- 新增文件：`static/demo_console.html`（重构，1200-1600 行）、`scripts/seed_data.py`（~200 行）、`scripts/seed_data/daily.yaml`、`scripts/seed_data/emergency.yaml`
- 无新依赖，无数据库 schema 变更（复用现有 incident_logs/push_logs 表，新 collection 仅在 ChromaDB 中）
- 所有端点仅在 `demo_router` 下，不影响生产路径
