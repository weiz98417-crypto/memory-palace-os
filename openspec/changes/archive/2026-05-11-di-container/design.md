## Context

`landing-refactor` 消除了模块级副作用，改为 `get_xxx_client()` 工厂函数。但 Orchestrator 和 Agent 内部仍有大量 lazy import（`from xxx import yyy`），无法 Mock 注入。同时 Phase 1 的 `context_tier.py` 和 `agent_memory.py` 处于 STUB 状态。

## Goals / Non-Goals

**Goals:**
- 手写 AppContainer，零外部依赖
- Orchestrator 从 Container 获取依赖，支持 Mock 注入
- 激活 context_tier.py（三层上下文构建）
- 激活 agent_memory.py（Agent 内存隔离 + scoped context）
- 每个 Agent 可注入 Mock Container 独立测试

**Non-Goals:**
- 不引入 pip 依赖（DI 库）
- 不改 API 端点
- 不改变 Agent 业务逻辑
- 不激活 Phase 2-4

## Decisions

### D1: Container 实现方式

选择：手写 `dataclass` + 懒加载 property。

```python
@dataclass
class AppContainer:
    _overrides: dict = field(default_factory=dict)

    @property
    def db_client(self):
        if "db_client" in self._overrides:
            return self._overrides["db_client"]
        from src.memory_palace.knowledge.db_client import db_client
        return db_client

    def override(self, **kwargs):
        self._overrides.update(kwargs)

    def reset(self):
        self._overrides.clear()
```

理由：每个 property 内部做 lazy import + override 检查。比 `dependency-injector` 简单 100 倍，零依赖，够用。

### D2: Orchestrator 改造

选择：`Orchestrator.__init__` 接受 `container: Optional[AppContainer] = None`，默认用全局 `container` 单例。所有内部 `from xxx import yyy` 改为 `self.container.xxx`。

理由：向后兼容——现有代码 `Orchestrator()` 不传参也能工作。测试时传 `Orchestrator(container=mock_container)`。

### D3: context_tier 激活策略

选择：`ContextTier` 类实现 `build_tiered_context(session_id, messages) -> dict`，按 Hot/Warm/Cold 三层返回。Hot 层原样保留最近 10 条，Warm 层 LLM 摘要，Cold 层叙事性摘要。

当前先用简化版：Hot 层正常工作，Warm/Cold 层返回空摘要。后续再接 LLM 摘要功能。

### D4: agent_memory 激活策略

选择：`AgentMemory` 类实现 `get_scoped_context(agent_name) -> dict`，根据 agent_name 过滤 fields。Router 只看 `raw_text`、`msg_id`，Commander 看 `raw_text`、`severity`、`from_user`。

## Risks / Trade-offs

- [Risk] Container property 每次访问都做 import 检查 → overhead 极小（Python import 有缓存）
- [Risk] context_tier Warm/Cold 层暂无 LLM 摘要 → 先返回空，后续迭代加
