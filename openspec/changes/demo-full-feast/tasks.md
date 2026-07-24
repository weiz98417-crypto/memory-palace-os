## 1. Backend: PersonaExtract 访谈 API

- [x] 1.1 PersonaExtractSkill 新增 `start_interview(job_title, venue_id, trace_id)` public wrapper（参数 reorder，total_questions=4）
- [x] 1.2 PersonaExtractSkill 新增 `continue_interview(interview_id, answer, trace_id)` public wrapper
- [x] 1.3 PersonaExtractSkill 新增 `finalize_interview(interview_id, trace_id)` public wrapper
- [x] 1.4 gateway.py 新增 `POST /demo/persona/interview/start` 端点
- [x] 1.5 gateway.py 新增 `POST /demo/persona/interview/continue` 端点
- [x] 1.6 gateway.py 新增 `POST /demo/persona/interview/finalize` 端点

## 2. Backend: Todo 分解 + 知识库 + Watcher + 场景

- [x] 2.1 orchestrator._route() 顶部新增 `demo_todo_decompose` msg_type 路由分支
- [x] 2.2 gateway.py 新增 `POST /demo/todo/decompose` 端点（队列派发模式）
- [x] 2.3 gateway.py 新增 `GET /demo/knowledge/search` 端点（查询 demo_knowledge collection）
- [x] 2.4 gateway.py 新增 `GET /demo/watcher-log` 端点（读 incident_logs + push_logs）
- [x] 2.5 gateway.py 新增 `GET /demo/scenario/switch` 端点

## 3. 种子数据

- [x] 3.1 创建 `scripts/seed_data/daily.yaml`（日常运营场景）
- [x] 3.2 创建 `scripts/seed_data/emergency.yaml`（突发事件场景）
- [x] 3.3 创建 `scripts/seed_data.py`（load_scenario 函数 + CLI）
- [x] 3.4 验证种子数据可正确导入 ChromaDB + SQLite

## 4. Frontend: 控制台重构

- [x] 4.1 重构 `demo_console.html` 为 6 标签页布局（消息链路、任务系统、访谈、知识库、监控、管理）
- [x] 4.2 实现 PersonaExtract 访谈 UI（start → Q&A 流 → finalize → 条目卡片）
- [x] 4.3 实现 Todo 依赖树渲染（CSS 缩进 + ├── └── 伪元素）
- [x] 4.4 实现 Pipeline 后置动画（setTimeout 300ms 间隔逐节点点亮）
- [x] 4.5 实现 Auto-play 引擎（时间线数组 + 超时兜底 + Play/Pause/Stop）
- [x] 4.6 实现知识库场景切换 + 搜索 UI
- [x] 4.7 实现 Watcher 巡检日志列表
- [x] 4.8 实现 @media print 报告导出样式

## 5. 验证

- [x] 5.1 `DEMO_MODE=true` 启动，确认所有 5 个新端点返回正确响应
- [x] 5.2 运行 `python scripts/seed_data.py --scenario daily` 确认种子数据导入成功
- [x] 5.3 运行 `python scripts/seed_data.py --scenario emergency` 确认场景切换正常
- [x] 5.4 控制台 6 标签页功能全部正常
- [x] 5.5 Auto-play 完整走完时间线无报错
- [x] 5.6 `pytest tests/ -v` 154 passed，无回归
