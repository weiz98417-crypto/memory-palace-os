## Context

`permissions.py` 和 `tool_executor.py` 已有完整实现，在 `landing-refactor` 中被退回了 STUB（`reload_from_db()` → no-op）。M2 修复了 DB 初始化顺序，现在表已存在。M3 恢复权限检查逻辑并接入 Container。

## Goals / Non-Goals

**Goals:**
- 恢复 `PermissionEngine.reload_from_db()` 真实实现
- 恢复 `ToolExecutor` 的权限检查 + 审计功能
- Container 注册两个新服务
- 工具调用走完整中间件链

**Non-Goals:**
- 不新增工具类型
- 不改审批 UI
- 不激活 Phase 3/4

## Decisions

### D1: 恢复策略

`permissions.py` 的 `reload_from_db()` 和 `tool_executor.py` 都是完整实现，STUB 时只改了 2 行（`pass` 替换了完整方法体）。恢复方式：从 git history 找回原始代码。

### D2: Container 接入

```python
# container.py
@property
def permission_engine(self):
    # 懒加载 PermissionEngine 单例

@property
def tool_executor(self):
    # 懒加载 ToolExecutor，注入 permission_engine 和 audit_logger
```

### D3: 中间件链

```
ToolCall
  → PermissionEngine.check(tool_name, args)
    → FREE: 直接执行
    → LOGGED: 执行 + 写 tool_invocation_logs
    → APPROVAL: 挂起 → 写 approval_requests → 等待 Admin 审批
  → ToolExecutor.execute(tool_name, args)
  → AuditLogger.log(tool_name, args, result)
```

## Risks / Trade-offs

- [Risk] 恢复的代码可能有未发现的 bug → 加集成测试覆盖
- [Risk] 审批流需企微通知 Admin → 企微未配置时静默降级
