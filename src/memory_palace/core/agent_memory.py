"""
Agent 内存隔离模块 (Agent Memory Isolation) — STUB: Phase 1，待激活

核心职责:
1. 为每个 Agent 维护独立的对话历史
2. 防止 Agent 之间的内存互相污染
3. 支持共享上下文 (shared_context) 用于必要的跨 Agent 信息传递

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class AgentMemoryTurn:
    """单次 Agent 内存记录"""
    agent_name: str
    timestamp: float
    input_text: str
    output_text: Optional[str]
    structured_data: Dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0


class AgentMemoryScope:
    """
    Agent 内存作用域管理器

    设计原则:
    - 每个 Agent 只能看到自己的对话历史
    - 共享信息必须通过显式的 shared_context 传递
    - 敏感字段 (如 router 的 raw_confidence) 不传递给下游 Agent
    """

    def __init__(self, max_history_per_agent: int = 50):
        # Agent 独立的内存缓存: {session_id: {agent_name: [AgentMemoryTurn]}}
        self._agent_memories: Dict[str, Dict[str, List[AgentMemoryTurn]]] = {}

        # 共享上下文 (跨 Agent 传递的信息)
        self._shared_context: Dict[str, Dict[str, Any]] = {}

        # 每个 Agent 的最大历史记录数
        self.max_history_per_agent = max_history_per_agent

    def push(
        self,
        session_id: str,
        agent_name: str,
        input_text: str,
        output_text: Optional[str] = None,
        structured_data: Optional[Dict[str, Any]] = None,
        tokens_used: int = 0
    ) -> None:
        """
        记录 Agent 的一次交互

        Args:
            session_id: 会话 ID
            agent_name: Agent 名称
            input_text: 用户输入
            output_text: Agent 输出
            structured_data: 结构化数据
            tokens_used: 消耗的 token 数
        """
        if session_id not in self._agent_memories:
            self._agent_memories[session_id] = {}

        if agent_name not in self._agent_memories[session_id]:
            self._agent_memories[session_id][agent_name] = []

        turn = AgentMemoryTurn(
            agent_name=agent_name,
            timestamp=time.time(),
            input_text=input_text,
            output_text=output_text,
            structured_data=structured_data or {},
            tokens_used=tokens_used
        )

        self._agent_memories[session_id][agent_name].append(turn)

        # 限制内存大小
        if len(self._agent_memories[session_id][agent_name]) > self.max_history_per_agent:
            self._agent_memories[session_id][agent_name] = \
                self._agent_memories[session_id][agent_name][-self.max_history_per_agent:]

        logger.debug(
            f"[AgentMemory] {agent_name} in {session_id}: "
            f"recorded turn, total {len(self._agent_memories[session_id][agent_name])} turns"
        )

    def get_history(
        self,
        session_id: str,
        agent_name: str,
        limit: int = 10
    ) -> List[Dict[str, str]]:
        """
        获取指定 Agent 的对话历史

        返回格式兼容 OpenAI Message:
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        if session_id not in self._agent_memories:
            return []

        agent_turns = self._agent_memories[session_id].get(agent_name, [])
        recent_turns = agent_turns[-limit:]

        result = []
        for turn in recent_turns:
            result.append({"role": "user", "content": turn.input_text})
            if turn.output_text:
                result.append({"role": "assistant", "content": turn.output_text})

        return result

    def get_all_agent_names(self, session_id: str) -> List[str]:
        """获取会话中所有 Agent 的名称"""
        if session_id not in self._agent_memories:
            return []
        return list(self._agent_memories[session_id].keys())

    def set_shared_context(
        self,
        session_id: str,
        key: str,
        value: Any
    ) -> None:
        """
        设置共享上下文

        用于: Router -> Commander 传递 case_id, severity 等必要信息
        """
        if session_id not in self._shared_context:
            self._shared_context[session_id] = {}

        self._shared_context[session_id][key] = value
        logger.debug(f"[AgentMemory] Shared context set: {session_id}/{key}")

    def get_shared_context(
        self,
        session_id: str,
        key: str,
        default: Any = None
    ) -> Any:
        """获取共享上下文"""
        return self._shared_context.get(session_id, {}).get(key, default)

    def get_all_shared_context(self, session_id: str) -> Dict[str, Any]:
        """获取会话的所有共享上下文"""
        return self._shared_context.get(session_id, {}).copy()

    def clear_session(self, session_id: str) -> None:
        """清理会话的所有内存"""
        self._agent_memories.pop(session_id, None)
        self._shared_context.pop(session_id, None)
        logger.debug(f"[AgentMemory] Cleared all memory for session: {session_id}")


class ScopedContextBuilder:
    """
    Scoped Context 构造器

    核心功能:
    1. Router 输出仅作为分发元数据，不原封传递给下游
    2. 每个 Agent 只收到必要的上下文字段
    3. 共享信息通过 shared_context 传递
    """

    # 各 Agent 的必要上下文字段白名单
    AGENT_CONTEXT_WHITELIST: Dict[str, List[str]] = {
        "router": [
            "raw_text", "msg_id", "from_user", "session_id", "trace_id"
        ],
        "commander": [
            "intent", "severity", "priority", "case_id",
            "msg_id", "from_user", "session_id", "trace_id"
        ],
        "watcher": [
            "audit_target_logs", "session_id", "trace_id"
        ],
        "persona": [
            "history", "persona_type", "msg_id", "from_user", "session_id", "trace_id"
        ],
        "memory_ops": [
            "operation", "raw_text", "msg_id", "from_user", "session_id", "trace_id"
        ],
        "commander_dispatch": [
            "dispatch_action", "case_id", "session_id", "trace_id"
        ]
    }

    def __init__(self, agent_memory: AgentMemoryScope):
        self.agent_memory = agent_memory

    def build_scoped_context(
        self,
        agent_name: str,
        session_id: str,
        base_context: Dict[str, Any],
        route_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        为指定 Agent 构建受限的上下文

        Args:
            agent_name: 目标 Agent 名称
            session_id: 会话 ID
            base_context: 基础上下文 (来自 orchestrator)
            route_result: 路由结果 (Router 的输出)

        Returns:
            仅包含必要字段的 scoped context
        """
        # 获取白名单字段
        whitelist = self.AGENT_CONTEXT_WHITELIST.get(agent_name, [])

        # 构建 scoped context
        scoped = {}

        # 1. 添加白名单中的基础字段
        for key in whitelist:
            if key in base_context:
                scoped[key] = base_context[key]

        # 2. 如果有 route_result，提取分发元数据
        if route_result and agent_name != "router":
            # Router 输出转换为分发元数据
            dispatch_metadata = self._extract_dispatch_metadata(route_result)

            for key in whitelist:
                if key in dispatch_metadata:
                    scoped[key] = dispatch_metadata[key]

        # 3. 添加 Agent 自己的历史 (persona 等需要)
        if agent_name == "persona":
            scoped["history"] = self.agent_memory.get_history(session_id, agent_name, limit=10)

        # 4. 添加共享上下文中的相关字段
        shared = self.agent_memory.get_all_shared_context(session_id)
        for key in whitelist:
            if key in shared:
                scoped[key] = shared[key]

        logger.debug(
            f"[ScopedContextBuilder] Built context for {agent_name}: "
            f"keys={list(scoped.keys())}"
        )

        return scoped

    def _extract_dispatch_metadata(
        self,
        route_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        从 Router 输出提取分发元数据

        原则:
        - 只提取下游 Agent 真正需要的字段
        - 丢弃 Router 的内部置信度、raw_output 等
        """
        metadata = {}

        # 标准分发字段
        standard_fields = [
            "intent", "severity", "priority", "target_agent",
            "case_id", "summary", "persona_type", "memory_operation"
        ]

        for field in standard_fields:
            if field in route_result:
                metadata[field] = route_result[field]

        return metadata

    def record_agent_turn(
        self,
        session_id: str,
        agent_name: str,
        input_text: str,
        output_text: Optional[str],
        structured_data: Optional[Dict[str, Any]] = None,
        tokens_used: int = 0
    ) -> None:
        """记录 Agent 交互并更新共享上下文"""
        # 记录到 Agent 内存
        self.agent_memory.push(
            session_id=session_id,
            agent_name=agent_name,
            input_text=input_text,
            output_text=output_text,
            structured_data=structured_data,
            tokens_used=tokens_used
        )

        # 如果有结构化数据，同步到共享上下文
        if structured_data:
            for key in ["case_id", "intent", "severity", "target_agent"]:
                if key in structured_data:
                    self.agent_memory.set_shared_context(session_id, key, structured_data[key])


# 全局 Agent 内存作用域实例
agent_memory_scope = AgentMemoryScope()


def get_agent_memory_scope() -> AgentMemoryScope:
    """获取全局 Agent 内存作用域"""
    return agent_memory_scope


def get_scoped_context_builder() -> ScopedContextBuilder:
    """获取全局 Scoped Context 构造器"""
    return ScopedContextBuilder(agent_memory_scope)
