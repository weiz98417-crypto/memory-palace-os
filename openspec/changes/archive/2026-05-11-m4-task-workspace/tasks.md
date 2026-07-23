# Tasks: M4 — 任务图 + 工作区隔离

## 1. TaskGraph 恢复

- [x] 1.1 `task_graph.py`：恢复 `reload_from_db()` 真实实现
- [x] 1.2 Container 注册 `task_graph` property

## 2. Workspace 接入

- [x] 2.1 确认 `workspace.py` 实现完整（无需改动）
- [x] 2.2 Container 注册 `workspace` property

## 3. 集成测试

- [x] 3.1 TaskGraph：reload_from_db 空表不报错
- [x] 3.2 Workspace：路径遍历检测通过，越界抛 ValueError

## 4. 验证

- [x] 4.1 `python -c "from main import app"` 无 error
- [x] 4.2 现有 27 个测试全 PASS
- [x] 4.3 新 5 个测试 PASS，合计 32/32 全 PASS
- [x] 4.4 Container 提供全部 10 个服务（最终架构 = C）
