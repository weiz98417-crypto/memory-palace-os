# Tasks: M2 — DI Container + Phase 1

## 1. Container 核心

- [x] 1.1 新建 `core/container.py`：AppContainer dataclass + 6 个懒加载 property
- [x] 1.2 Container 加 `override()` 和 `reset()` 方法
- [x] 1.3 全局单例 `container = AppContainer()`
- [x] 1.4 验证：导入不触发 ChromaDB/LLM，`_instances` 和 `_overrides` 均为空

## 2. Orchestrator 改造

- [x] 2.1 `Orchestrator.__init__` 接受 `container` 参数（默认全局单例）
- [x] 2.2 `_save_message()` 保持不变（模块级函数，不归 Container 管）
- [x] 2.3 `_route()` 中 `get_skill_by_name()` 保持不变
- [x] 2.4 `_update_sla_response()` 保持不变（模块级函数）
- [x] 2.5 `_get_scoped_builder()` 改为 `self.container.agent_memory`

## 3. ContextTier 激活

- [x] 3.1 `context_tier.py`：已有完整 `ContextCompressor` 实现（非 STUB）
- [x] 3.2 新增 `build_tiered_context()` 方法（Hot/Warm/Cold 三层接口）
- [x] 3.3 Warm/Cold 层暂返回空（LLM 摘要后续迭代），加 TODO 注释
- [x] 3.4 Container 注册 context_tier → 使用 `context_compressor` 单例

## 4. AgentMemory 激活

- [x] 4.1 `agent_memory.py`：已有完整 `AgentMemoryScope` + `ScopedContextBuilder`（非 STUB）
- [x] 4.2 `build_scoped_context()` 已实现，按 agent 过滤字段
- [x] 4.3 `record_agent_turn()` → 已有 `AgentMemoryScope.push()`
- [x] 4.4 Container 注册 agent_memory → 使用 `get_scoped_context_builder()` 单例

## 5. DI 集成测试

- [x] 5.1 Container import 无副作用 + override/reset/cache
- [x] 5.2 Orchestrator 接受自定义 Container（Mock 注入）
- [x] 5.3 ContextTier：25 条消息 → Hot 10 条，Warm/Cold 空
- [x] 5.4 AgentMemory：Router 不拿 severity 字段 + turn 隔离

## 6. 验证

- [x] 6.1 `python -c "from main import app"` 无 error
- [x] 6.2 现有 12 个测试全 PASS
- [x] 6.3 新 8 个 DI 测试 PASS
- [x] 6.4 合计 20/20 全 PASS
