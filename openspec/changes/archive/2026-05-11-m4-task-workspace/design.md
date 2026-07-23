## Context

M4 是演进路线的最后一个里程碑。`task_graph.py` 的 `reload_from_db()` 在 `landing-refactor` 中被改为 STUB，现在恢复。`workspace.py` 从未被 STUB，保持完整。两者接入 Container 后达到最终架构。

## Goals / Non-Goals

**Goals:**
- 恢复 `task_graph.reload_from_db()` 真实实现
- Container 注册 task_graph 和 workspace
- 路径遍历攻击防护可验证

**Non-Goals:**
- 不新增任务类型
- 不改变工作区目录结构
- 这是演进路线的最后一个里程碑

## Decisions

### D1: 恢复策略

与 M3 相同：`task_graph.reload_from_db()` 从 git/当前代码找回原始实现（完整代码在 STUB 之前就已存在）。

### D2: 最终架构

```
Container
  ├── db_client         (SQLite)
  ├── vector_store      (ChromaDB)
  ├── llm_client        (DeepSeek)
  ├── wechat_client     (企微)
  ├── context_tier      (Phase 1)
  ├── agent_memory      (Phase 1)
  ├── permission_engine (Phase 2)
  ├── tool_executor     (Phase 2)
  ├── task_graph        (Phase 3)  ← NEW
  └── workspace         (Phase 4)  ← NEW
```

至此 6 个 Phase 能力全部接入 Container，达到设计文档中的 C 级架构。
