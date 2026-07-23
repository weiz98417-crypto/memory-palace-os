## Why

M3 完成了权限引擎和工具执行器。现在只剩最后两个 Phase：任务依赖图（Phase 3）和工作区隔离（Phase 4）。两个模块都有完整实现，只需从 STUB 恢复并接入 Container。完成后达到设计文档中的最终架构（=C）。

## What Changes

- 恢复 `task_graph.py`：`reload_from_db()` 从 STUB 恢复
- `workspace.py` 已完整实现，无需改动
- Container 注册 `task_graph` 和 `workspace` property
- 新增集成测试：任务图恢复、工作区隔离

## Capabilities

### New Capabilities
- `task-graph`: 任务依赖图持久化，Docker 重启后 PENDING 任务自动恢复
- `workspace`: 工作区沙盒隔离，路径遍历攻击防护

## Impact

- 修改：`core/task_graph.py`（STUB→激活），`core/container.py`（加 2 property）
- `core/workspace.py` 已完整，无需修改
- DB 表 `tasks` 已建好，无需迁移
