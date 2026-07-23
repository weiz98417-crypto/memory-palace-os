## Why

M2 建立了 DI Container 和 Phase 1，Agent 可独立测试。但 tool_executor.py 和 permissions.py 仍处于 STUB 状态——破坏性操作（短信/企微推送）无审批控制，工具调用无审计日志。M3 激活 Phase 2：权限引擎 + 工具执行器，建立 `ToolCall → PermissionCheck → Execute → AuditLog` 中间件链。

## What Changes

- 激活 `permissions.py`：保留现有实现，`reload_from_db()` 从 STUB 恢复（M2 的 Container 让 DB 初始化顺序已正确）
- 激活 `tool_executor.py`：将权限检查钩子接入工具执行流程
- Container 注册 `permission_engine` 和 `tool_executor`
- 接入现有审批请求表和工具调用日志表（已在 `db_init.py` 建好）
- 新增权限引擎集成测试

## Capabilities

### New Capabilities
- `permission-engine`: FREE/LOGGED/APPROVAL 三级权限，APPROVAL 操作挂起等审批
- `tool-executor`: 工具注册 + 权限检查 + 执行 + 审计日志，中间件链模式

### Modified Capabilities
_无（不改已有 capability 的外部行为）_

## Impact

- 修改：`core/permissions.py`（STUB→激活），`core/tool_executor.py`（STUB→激活），`core/container.py`（加 2 个 property）
- 不影响：API 端点、Agent 业务逻辑
- DB 表 `approval_requests`、`tool_invocation_logs` 已建好，无需迁移
