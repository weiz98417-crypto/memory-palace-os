## Why

核心链路已跑通，但存在两个结构性问题：1) Orchestrator 和 Agent 内部到处 `from xxx import yyy`，紧耦合，无法对单个 Agent 做单元测试；2) 所有 Agent 共享同一个 flat context dict，信息互相污染。需要引入轻量 DI Container 统一管理依赖，激活 Phase 1（上下文压缩 + Agent 内存隔离），让每个 Agent 可独立测试、只看到自己的上下文。

## What Changes

- 新建 `core/container.py`：手写 AppContainer 类（~50 行，零外部依赖），管理 db_client、vector_store、llm_client、wechat_client 等单例
- Container 支持 `override()` 注入 Mock 用于测试，支持 `reset()` 清理状态
- `Orchestrator.__init__` 接受可选 Container 参数，默认用全局单例
- Orchestrator 内部的 lazy import 全部改为从 Container 取
- 激活 `context_tier.py`：实现 Hot/Warm/Cold 三层上下文构建
- 激活 `agent_memory.py`：实现 scoped context builder，每个 Agent 只收必要字段
- 现有 `get_xxx_client()` 工厂函数保持不变，Container 内部调用它们
- 新增 DI 注入测试：Mock Container → Agent 独立运行

## Capabilities

### New Capabilities
- `app-container`: 轻量 DI Container，统一管理所有服务依赖，支持 Mock 注入
- `context-tier`: 三层上下文压缩系统（Hot/Warm/Cold tiering）
- `agent-memory`: Agent 内存隔离，每个 Agent 独立对话历史 + scoped context

### Modified Capabilities
_无（不改变已有 capability 的外部行为）_

## Impact

- 新建：`core/container.py`
- 修改：`core/orchestrator.py`（接受 Container），`core/context_tier.py`（从 STUB 激活），`core/agent_memory.py`（从 STUB 激活）
- 不影响：所有 API 端点、Agent 业务逻辑、外部接口
- 现有 `get_xxx_client()` 全部保留，向后兼容
