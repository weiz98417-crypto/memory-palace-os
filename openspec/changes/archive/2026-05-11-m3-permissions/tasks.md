# Tasks: M3 — 权限引擎 + 工具执行器

## 1. Permission Engine 恢复

- [x] 1.1 `permissions.py`：恢复 `reload_from_db()` 真实实现
- [x] 1.2 确认 `approval_requests` 表存在且可读写（已在 db_init.py 建好）
- [x] 1.3 Container 注册 `permission_engine` property

## 2. Tool Executor 恢复

- [x] 2.1 `tool_executor.py`：修复 `VectorStore` → `get_vector_client()`，`vs.search()` → `vs.query_experience()`
- [x] 2.2 确认 `tool_invocation_logs` 表可写入（已在 db_init.py 建好）
- [x] 2.3 Container 注册 `tool_executor` property

## 3. 集成测试

- [x] 3.1 FREE 工具：级别正确，check_and_execute 正常执行
- [x] 3.2 LOGGED 工具：级别正确
- [x] 3.3 APPROVAL 工具：级别正确，check_and_execute 返回 pending_approval

## 4. 验证

- [x] 4.1 `python -c "from main import app"` 无 error
- [x] 4.2 启动日志无 error，权限引擎恢复成功
- [x] 4.3 现有 20 个测试全 PASS
- [x] 4.4 新 7 个权限测试 PASS，合计 27/27 全 PASS
