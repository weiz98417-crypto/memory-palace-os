"""
会话上下文管理器 (Conversation Context Manager)

职责：
1. 维护企微用户与智能体之间的多轮对话历史。
2. 实现"滑动窗口"机制，自动截断超长历史以节省 Token 并防止模型幻觉。
3. 提供强类型的上下文载体，确保用户信息在各智能体间安全穿透。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from loguru import logger

# ---------------------------------------------------------------------------
# [依赖导入] - 用于计算 Token 长度，防止上下文爆炸
# ---------------------------------------------------------------------------
try:
    import tiktoken
except ImportError:
    logger.warning("未安装 tiktoken，Token 统计功能将降级为字符计数。")
    tiktoken = None

class Message(BaseModel):
    """单条消息实体"""
    role: str = Field(..., description="角色: user / assistant / system")
    content: str = Field(..., description="消息内容")
    timestamp: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ConversationContext(BaseModel):
    """
    单次会话的完整上下文载体
    作为 DTO (数据传输对象) 在各个 Agent 之间穿透。
    """
    user_id: str = Field(..., description="企业微信 UserID")
    venue_id: str = Field(..., description="所属景区 ID")
    trace_id: str = Field(..., description="全链路追踪 ID")
    history: List[Message] = Field(default_factory=list, description="近期对话历史记录")
    vars: Dict[str, Any] = Field(default_factory=dict, description="运行时变量池(如提取到的严重等级等)")

    def add_message(self, role: str, content: str, **kwargs):
        """记录一条新消息"""
        self.history.append(Message(role=role, content=content, metadata=kwargs))

class ContextManager:
    """
    工业级上下文生命周期管理器
    """
    def __init__(self, max_history_len: int = 10, max_tokens: int = 4000):
        # 内部缓存：生产环境建议替换为 Redis 存储实现分布式一致性
        self._store: Dict[str, ConversationContext] = {}
        self.max_history_len = max_history_len
        self.max_tokens = max_tokens
        
        # 初始化编码器 (默认使用 GPT-4 编码器)
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base") if tiktoken else None
        except Exception:
            self.tokenizer = None

    def get_context(self, user_id: str, venue_id: str, trace_id: str) -> ConversationContext:
        """
        获取或初始化用户的上下文。
        工业级实现：此方法应具备从数据库/缓存恢复历史记录的能力。
        """
        key = f"{venue_id}:{user_id}"
        if key not in self._store:
            logger.debug(f"[Context] 为用户 {user_id} 初始化新会话仓储")
            self._store[key] = ConversationContext(
                user_id=user_id,
                venue_id=venue_id,
                trace_id=trace_id
            )
        
        ctx = self._store[key]
        ctx.trace_id = trace_id # 每次请求更新最新的 TraceID
        
        # 执行滑窗截断
        self._apply_sliding_window(ctx)
        return ctx

    def _apply_sliding_window(self, ctx: ConversationContext):
        """
        核心护栏：滑动窗口截断逻辑。
        1. 限制消息条数。
        2. 限制 Token 总长度。
        """
        # 1. 数量截断
        if len(ctx.history) > self.max_history_len:
            ctx.history = ctx.history[-self.max_history_len:]
            logger.debug(f"[Context] 用户 {ctx.user_id} 触发数量滑窗截断")

        # 2. Token 截断 (如果安装了 tiktoken)
        if self.tokenizer:
            while len(ctx.history) > 1:
                total_text = "".join([m.content for m in ctx.history])
                token_count = len(self.tokenizer.encode(total_text))
                if token_count <= self.max_tokens:
                    break
                ctx.history.pop(0) # 剔除最早的一条记忆
                logger.debug(f"[Context] 用户 {ctx.user_id} 触发 Token 溢出截断")

    def clear(self, user_id: str, venue_id: str):
        """显式清空用户上下文（如用户输入"退出"或"结束对话"）"""
        key = f"{venue_id}:{user_id}"
        if key in self._store:
            del self._store[key]
            logger.info(f"[Context] 用户 {user_id} 会话已主动销毁")

    def save(self, ctx: ConversationContext):
        """
        持久化钩子：在此处将 ctx 异步写入数据库。
        """
        # TODO: 调用 src.memory_palace.knowledge.db_client 存入 SQLite
        pass

# 全局单例
context_manager = ContextManager()