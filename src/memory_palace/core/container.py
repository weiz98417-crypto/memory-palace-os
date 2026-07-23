"""
AppContainer — 轻量依赖注入容器

设计原则：
- 零外部依赖，手写 dataclass + 懒加载 @property
- 每个 property 首次访问时创建单例，后续返回缓存
- override() 注入 Mock 用于测试，reset() 恢复
- 全局 container 单例，Orchestrator 可接受可选 container 参数

用法：
  from src.memory_palace.core.container import container

  # 正常使用
  db = container.db_client

  # 测试注入
  container.override(llm_client=mock_llm)
  # ... test ...
  container.reset()

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AppContainer:
    """统一管理所有服务单例的轻量 DI 容器。"""

    _overrides: Dict[str, Any] = field(default_factory=dict)
    _instances: Dict[str, Any] = field(default_factory=dict)

    # ── 数据库 ──────────────────────────────────────────────────────────────

    @property
    def db_client(self):
        if "db_client" in self._overrides:
            return self._overrides["db_client"]
        if "db_client" not in self._instances:
            from src.memory_palace.knowledge.db_client import db_client
            self._instances["db_client"] = db_client
        return self._instances["db_client"]

    # ── 向量库 ──────────────────────────────────────────────────────────────

    @property
    def vector_store(self):
        if "vector_store" in self._overrides:
            return self._overrides["vector_store"]
        if "vector_store" not in self._instances:
            from src.memory_palace.knowledge.vector_store import get_vector_client
            self._instances["vector_store"] = get_vector_client()
        return self._instances["vector_store"]

    # ── LLM 客户端 ───────────────────────────────────────────────────────────

    @property
    def llm_client(self):
        if "llm_client" in self._overrides:
            return self._overrides["llm_client"]
        if "llm_client" not in self._instances:
            from src.memory_palace.tools.llm_wrapper import llm_client
            self._instances["llm_client"] = llm_client
        return self._instances["llm_client"]

    # ── 企微客户端 ───────────────────────────────────────────────────────────

    @property
    def wechat_client(self):
        if "wechat_client" in self._overrides:
            return self._overrides["wechat_client"]
        if "wechat_client" not in self._instances:
            from src.memory_palace.tools.wechat_client import get_wechat_client
            self._instances["wechat_client"] = get_wechat_client()
        return self._instances["wechat_client"]

    # ── 上下文压缩 (Phase 1) ────────────────────────────────────────────────

    @property
    def context_tier(self):
        if "context_tier" in self._overrides:
            return self._overrides["context_tier"]
        if "context_tier" not in self._instances:
            from src.memory_palace.core.context_tier import context_compressor
            self._instances["context_tier"] = context_compressor
        return self._instances["context_tier"]

    # ── Agent 内存隔离 (Phase 1) ─────────────────────────────────────────────

    @property
    def agent_memory(self):
        if "agent_memory" in self._overrides:
            return self._overrides["agent_memory"]
        if "agent_memory" not in self._instances:
            from src.memory_palace.core.agent_memory import get_scoped_context_builder
            self._instances["agent_memory"] = get_scoped_context_builder()
        return self._instances["agent_memory"]

    # ── 权限引擎 (Phase 2) ─────────────────────────────────────────────────

    @property
    def permission_engine(self):
        if "permission_engine" in self._overrides:
            return self._overrides["permission_engine"]
        if "permission_engine" not in self._instances:
            from src.memory_palace.core.permissions import permission_engine
            self._instances["permission_engine"] = permission_engine
        return self._instances["permission_engine"]

    # ── 工具执行器 (Phase 2) ─────────────────────────────────────────────────

    @property
    def tool_executor(self):
        if "tool_executor" in self._overrides:
            return self._overrides["tool_executor"]
        if "tool_executor" not in self._instances:
            import src.memory_palace.tools.tool_executor as _te
            self._instances["tool_executor"] = _te
        return self._instances["tool_executor"]

    # ── 任务依赖图 (Phase 3) ─────────────────────────────────────────────────

    @property
    def task_graph(self):
        if "task_graph" in self._overrides:
            return self._overrides["task_graph"]
        if "task_graph" not in self._instances:
            from src.memory_palace.core.task_graph import task_graph
            self._instances["task_graph"] = task_graph
        return self._instances["task_graph"]

    # ── 工作区隔离 (Phase 4) ─────────────────────────────────────────────────

    @property
    def workspace(self):
        if "workspace" in self._overrides:
            return self._overrides["workspace"]
        if "workspace" not in self._instances:
            from src.memory_palace.core.workspace import workspace_manager
            self._instances["workspace"] = workspace_manager
        return self._instances["workspace"]

    # ── 测试支持 ────────────────────────────────────────────────────────────

    def override(self, **kwargs):
        """注入 Mock 实例用于测试。e.g. container.override(llm_client=mock_llm)"""
        self._overrides.update(kwargs)

    def reset(self):
        """清除所有 override 和缓存，恢复原始行为。"""
        self._overrides.clear()
        self._instances.clear()


# 全局单例
container = AppContainer()
