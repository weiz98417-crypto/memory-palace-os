"""
会话状态管理器 (Session State Manager)

核心职责：
1. 用户会话生命周期管理：跟踪用户与系统的多轮交互状态
2. Agent 上下文传递：Router → Commander → Persona 的状态机流转
3. 滑动窗口历史：为 Persona 等需要历史记忆的 Agent 提供对话上下文
4. 分布式安全：支持 SQLite/Redis 后端，重启不丢状态

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import json
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

from loguru import logger

try:
    from ..knowledge.db_client import db_client
except ImportError:
    logger.warning("db_client 未初始化，session_state 将使用内存模式")
    db_client = None


class ConversationStage(str, Enum):
    """会话阶段枚举"""
    IDLE = "idle"                    # 空闲，等待新消息
    ROUTER_IDENTIFIED = "router_identified"  # Router 已识别意图
    COMMANDER_DISPATCHED = "commander_dispatched"  # Commander 已下发指令
    PERSONA_INTERVIEWING = "persona_interviewing"  # Persona 深度交互中
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # 等待用户确认/反馈
    CLOSED = "closed"                # 会话已闭环


@dataclass
class AgentTurn:
    """单次 Agent 交互记录"""
    agent_name: str                  # 哪个 Agent 处理的
    timestamp: float                 # Unix 时间戳
    input_text: str                  # 用户输入
    output_text: Optional[str]       # Agent 输出
    structured_data: Dict[str, Any]  # 结构化数据（意图、等级等）
    tokens_used: int = 0             # Token 消耗


@dataclass
class SessionState:
    """
    用户会话状态数据类
    
    字段设计原则：
    - 所有 Agent 需要共享的上下文放这里
    - 大字段（如完整历史）单独存储，主记录保持轻量
    """
    user_id: str                     # 企微 UserID
    session_id: str                  # 会话唯一标识（每次新事件生成）
    stage: ConversationStage         # 当前阶段
    created_at: float                # 会话创建时间
    updated_at: float                # 最后更新时间
    current_intent: Optional[str] = None      # 当前识别出的意图
    current_severity: Optional[str] = None    # 当前 P 等级（P0-P4）
    active_agent: Optional[str] = None        # 当前激活的 Agent
    context_payload: Dict[str, Any] = None    # 额外的上下文数据（如 case_id）
    history_summary: str = ""                 # 历史对话摘要（压缩后）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "stage": self.stage.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_intent": self.current_intent,
            "current_severity": self.current_severity,
            "active_agent": self.active_agent,
            "context_payload": json.dumps(self.context_payload) if self.context_payload else "{}",
            "history_summary": self.history_summary
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(
            user_id=data["user_id"],
            session_id=data["session_id"],
            stage=ConversationStage(data["stage"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            current_intent=data.get("current_intent"),
            current_severity=data.get("current_severity"),
            active_agent=data.get("active_agent"),
            context_payload=json.loads(data.get("context_payload", "{}")),
            history_summary=data.get("history_summary", "")
        )


class SessionStateManager:
    """
    会话状态管理器（异步单例）
    
    使用示例：
        manager = SessionStateManager()
        session = await manager.get_or_create_session(user_id="ZhouWei")
        await manager.update_stage(session.session_id, ConversationStage.COMMANDER_DISPATCHED)
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._memory_cache: Dict[str, SessionState] = {}  # 内存缓存（降级用）
        self._history_cache: Dict[str, List[AgentTurn]] = {}  # 对话历史缓存
        self._initialized = True
        
        logger.info("SessionStateManager 初始化完成")
    
    def _generate_session_id(self, user_id: str) -> str:
        """生成会话 ID：user_id + 时间戳"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{user_id}_{timestamp}"
    
    async def get_or_create_session(
        self, 
        user_id: str, 
        force_new: bool = False
    ) -> SessionState:
        """
        获取或创建用户会话
        
        Args:
            user_id: 企微用户 ID
            force_new: 是否强制创建新会话（用于全新事件）
        
        Returns:
            SessionState 对象
        """
        now = time.time()
        
        # 1. 尝试恢复现有活跃会话（30分钟内有过交互）
        if not force_new and db_client:
            try:
                existing = await db_client.fetch_one(
                    """
                    SELECT * FROM sessions 
                    WHERE user_id = ? AND stage != ? AND updated_at > ?
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (user_id, ConversationStage.CLOSED.value, now - 1800)
                )
                
                if existing:
                    session = SessionState.from_dict(dict(existing))
                    logger.debug(f"恢复现有会话: {session.session_id}")
                    return session
                    
            except Exception as e:
                logger.warning(f"数据库查询失败，降级到内存模式: {e}")
        
        # 2. 创建新会话
        session = SessionState(
            user_id=user_id,
            session_id=self._generate_session_id(user_id),
            stage=ConversationStage.IDLE,
            created_at=now,
            updated_at=now
        )
        
        # 3. 持久化
        await self._persist_session(session)
        
        logger.info(f"创建新会话: {session.session_id} for user: {user_id}")
        return session
    
    async def update_stage(
        self, 
        session_id: str, 
        new_stage: ConversationStage,
        agent_name: Optional[str] = None,
        context_update: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        更新会话阶段（状态机推进）
        
        这是 Orchestrator 调用最频繁的方法，用于推进 Agent 流转
        """
        session = await self.get_session(session_id)
        if not session:
            logger.error(f"尝试更新不存在的会话: {session_id}")
            return
        
        old_stage = session.stage
        session.stage = new_stage
        session.updated_at = time.time()
        
        if agent_name:
            session.active_agent = agent_name
        
        if context_update:
            if session.context_payload is None:
                session.context_payload = {}
            session.context_payload.update(context_update)
        
        await self._persist_session(session)
        
        logger.info(
            f"会话 {session_id} 状态推进: {old_stage.value} -> {new_stage.value} "
            f"(Agent: {agent_name})"
        )
    
    async def record_turn(
        self,
        session_id: str,
        agent_name: str,
        input_text: str,
        output_text: Optional[str],
        structured_data: Dict[str, Any],
        tokens_used: int = 0
    ) -> None:
        """
        记录一次 Agent 交互（用于历史追溯和 Persona 的滑动窗口）
        """
        turn = AgentTurn(
            agent_name=agent_name,
            timestamp=time.time(),
            input_text=input_text,
            output_text=output_text,
            structured_data=structured_data,
            tokens_used=tokens_used
        )
        
        # 1. 更新内存缓存
        if session_id not in self._history_cache:
            self._history_cache[session_id] = []
        self._history_cache[session_id].append(turn)
        
        # 2. 限制内存缓存大小（防泄漏）
        if len(self._history_cache[session_id]) > 50:
            self._history_cache[session_id] = self._history_cache[session_id][-50:]
        
        # 3. 持久化到数据库
        if db_client:
            try:
                await db_client.execute(
                    """
                    INSERT INTO conversation_turns 
                    (session_id, agent_name, timestamp, input_text, output_text, 
                     structured_data, tokens_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id, agent_name, turn.timestamp, input_text,
                        output_text, json.dumps(structured_data), tokens_used
                    )
                )
            except Exception as e:
                logger.error(f"持久化对话轮次失败: {e}")
        
        # 4. 更新会话摘要（用于快速恢复上下文）
        await self._update_history_summary(session_id)
    
    async def get_conversation_history(
        self, 
        session_id: str, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取对话历史（供 Persona 等 Agent 使用）
        
        返回格式兼容 OpenAI Message 格式：
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        # 优先从内存获取
        if session_id in self._history_cache:
            turns = self._history_cache[session_id][-limit:]
            return self._format_history(turns)
        
        # 从数据库恢复
        if db_client:
            try:
                rows = await db_client.fetch_all(
                    """
                    SELECT * FROM conversation_turns 
                    WHERE session_id = ? 
                    ORDER BY timestamp DESC LIMIT ?
                    """,
                    (session_id, limit)
                )
                turns = [AgentTurn(
                    agent_name=row["agent_name"],
                    timestamp=row["timestamp"],
                    input_text=row["input_text"],
                    output_text=row["output_text"],
                    structured_data=json.loads(row["structured_data"]),
                    tokens_used=row["tokens_used"]
                ) for row in rows]
                return self._format_history(reversed(turns))
            except Exception as e:
                logger.error(f"查询历史失败: {e}")
        
        return []
    
    def _format_history(self, turns: List[AgentTurn]) -> List[Dict[str, str]]:
        """格式化为标准对话格式"""
        history = []
        for turn in turns:
            history.append({"role": "user", "content": turn.input_text})
            if turn.output_text:
                history.append({"role": "assistant", "content": turn.output_text})
        return history
    
    async def get_session(self, session_id: str) -> Optional[SessionState]:
        """获取指定会话"""
        # 1. 内存缓存
        if session_id in self._memory_cache:
            return self._memory_cache[session_id]
        
        # 2. 数据库查询
        if db_client:
            try:
                row = await db_client.fetch_one(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (session_id,)
                )
                if row:
                    session = SessionState.from_dict(dict(row))
                    self._memory_cache[session_id] = session
                    return session
            except Exception as e:
                logger.error(f"查询会话失败: {e}")
        
        return None
    
    async def close_session(self, session_id: str, reason: str = "completed") -> None:
        """关闭会话"""
        session = await self.get_session(session_id)
        if session:
            session.stage = ConversationStage.CLOSED
            session.updated_at = time.time()
            await self._persist_session(session)
            
            # 清理内存缓存
            self._memory_cache.pop(session_id, None)
            self._history_cache.pop(session_id, None)
            
            logger.info(f"会话 {session_id} 已关闭，原因: {reason}")
    
    async def _persist_session(self, session: SessionState) -> None:
        """持久化会话状态"""
        # 1. 更新内存
        self._memory_cache[session.session_id] = session
        
        # 2. 更新数据库
        if db_client:
            try:
                data = session.to_dict()
                await db_client.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                    (session_id, user_id, stage, created_at, updated_at,
                     current_intent, current_severity, active_agent,
                     context_payload, history_summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["session_id"], data["user_id"], data["stage"],
                        data["created_at"], data["updated_at"],
                        data.get("current_intent"), data.get("current_severity"),
                        data.get("active_agent"),
                        data.get("context_payload", "{}"),
                        data.get("history_summary", "")
                    )
                )
            except Exception as e:
                logger.error(f"持久化会话失败: {e}")
    
    async def _update_history_summary(self, session_id: str) -> None:
        """更新历史摘要（用于快速上下文恢复）"""
        # 简单实现：取最近3轮的关键信息
        history = await self.get_conversation_history(session_id, limit=3)
        if not history:
            return
        
        summary_parts = []
        for msg in history[-6:]:  # 最近3轮 = 6条消息
            role = "员工" if msg["role"] == "user" else "系统"
            content = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
            summary_parts.append(f"[{role}]: {content}")
        
        session = await self.get_session(session_id)
        if session:
            session.history_summary = "\n".join(summary_parts)
            await self._persist_session(session)


# 全局单例
session_manager = SessionStateManager()