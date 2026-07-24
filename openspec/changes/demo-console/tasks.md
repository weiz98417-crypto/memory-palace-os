## 1. 后端端点

- [x] 1.1 在 `gateway.py` demo_router 中新增 `GET /demo/stats`：聚合 queue_depth、message_count、task_count、skills_registered、last_watcher_run
- [x] 1.2 在 `gateway.py` demo_router 中新增 `GET /demo/tasks`：返回 TaskGraph 中所有任务（id、description、status、dependencies、assigned_agent、session_id）

## 2. 演示控制台 HTML

- [x] 2.1 创建 `static/demo_console.html` 基础骨架：5 标签页布局 + 标题栏 + 状态栏
- [x] 2.2 实现"消息链路"标签页：预设消息按钮、自定义输入、POST /demo/send + 轮询 GET /demo/result、Pipeline 可视化（Stage1→Stage2→Router→Agent 流程图）、回复展示
- [x] 2.3 实现"任务系统"标签页：调用 GET /demo/tasks、任务卡片列表（状态+描述+依赖）、依赖关系树形展示
- [x] 2.4 实现"知识库"标签页：搜索框、调用 GET /v1/knowledge/query、结果列表展示
- [x] 2.5 实现"系统监控"标签页：调用 GET /demo/stats、仪表盘卡片（队列深度/消息数/任务数/技能数/巡检时间）
- [x] 2.6 实现"管理"标签页：关键数据摘要 + 跳转链接到管理大屏

## 3. 演示脚本

- [x] 3.1 创建 `scripts/demo.sh`：分幕脚本，支持 `./scripts/demo.sh scene1|scene2|scene3|scene4|scene5|all`
- [x] 3.2 预设 5 幕消息：紧急事件→Commander、日常咨询→Persona、任务分解→Todo/TaskGraph、知识检索→MemoryOps、多轮对话→PersonaExtract

## 4. 验证

- [x] 4.1 `DEMO_MODE=true` 启动服务，确认 `/admin/demo_console.html` 可访问
- [x] 4.2 所有 5 个标签页功能正常，API 调用返回正确数据
- [x] 4.3 `scripts/demo.sh` 全部 5 幕脚本执行成功
- [x] 4.4 `pytest tests/ -v` 全量测试通过（不引入回归）
