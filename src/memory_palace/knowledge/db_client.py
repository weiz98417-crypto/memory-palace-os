"""
数据库客户端 (Knowledge DB Client) - 异步原始 SQL 版本

核心特性：
1. 原始 SQL 接口：直接执行 SQL，无 ORM 开销
2. 异步非阻塞：基于 aiosqlite
3. 连接池管理：自动连接复用

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import aiosqlite
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager
from loguru import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = _PROJECT_ROOT / "data" / "memory.db"


class AsyncDBClient:
    """
    异步数据库客户端（原始 SQL）
    
    使用示例：
        db = AsyncDBClient()
        row = await db.fetch_one("SELECT * FROM sessions WHERE session_id = ?", (sid,))
        await db.execute("INSERT INTO sessions (...) VALUES (...)", (...,))
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def _get_connection(self) -> aiosqlite.Connection:
        """获取或创建连接"""
        if self._connection is None:
            self._connection = await aiosqlite.connect(str(self.db_path))
            self._connection.row_factory = aiosqlite.Row
        return self._connection

    @asynccontextmanager
    async def transaction(self):
        """事务上下文管理器"""
        conn = await self._get_connection()
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def execute(self, sql: str, parameters: tuple = ()) -> int:
        """
        执行 INSERT/UPDATE/DELETE
        返回：影响行数
        """
        async with self.transaction() as conn:
            cursor = await conn.execute(sql, parameters)
            return cursor.rowcount

    async def fetch_one(self, sql: str, parameters: tuple = ()) -> Optional[Dict[str, Any]]:
        """查询单条记录"""
        conn = await self._get_connection()
        cursor = await conn.execute(sql, parameters)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetch_all(self, sql: str, parameters: tuple = ()) -> List[Dict[str, Any]]:
        """查询多条记录"""
        conn = await self._get_connection()
        cursor = await conn.execute(sql, parameters)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def close(self):
        """关闭连接"""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("数据库连接已关闭")


# 全局单例（供 session_state.py 使用）
db_client = AsyncDBClient()


# 兼容性别名（如果你其他代码用了 db_manager）
db_manager = db_client


# ─────────────────────────────────────────────────────────────────────────────
# Additional convenience methods used by API endpoints
# ─────────────────────────────────────────────────────────────────────────────

async def check_connection() -> bool:
    """检查数据库连接是否正常"""
    try:
        row = await db_client.fetch_one("SELECT 1 as ok")
        return row is not None
    except Exception:
        return False


async def get_message(message_id: str) -> Optional[Dict[str, Any]]:
    """根据 message_id 获取消息"""
    return await db_client.fetch_one(
        "SELECT * FROM messages WHERE message_id = ?", (message_id,)
    )


async def get_messages(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """获取会话消息列表"""
    return await db_client.fetch_all(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (session_id, limit),
    )


async def get_sessions(user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """获取会话列表"""
    if user_id:
        return await db_client.fetch_all(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        )
    return await db_client.fetch_all(
        "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
    )


async def get_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    """根据 session_id 获取会话"""
    return await db_client.fetch_one(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    )


async def get_stats() -> Dict[str, Any]:
    """获取系统统计"""
    try:
        msg_count = await db_client.fetch_one("SELECT COUNT(*) as count FROM messages")
        sess_count = await db_client.fetch_one("SELECT COUNT(*) as count FROM sessions")
        return {
            "total_messages": msg_count["count"] if msg_count else 0,
            "total_sessions": sess_count["count"] if sess_count else 0,
        }
    except Exception:
        return {"total_messages": 0, "total_sessions": 0}


async def get_message_by_id(msg_id: str) -> Optional[Dict[str, Any]]:
    """根据 msg_id 获取消息 (gateway 兼容)"""
    return await db_client.fetch_one(
        "SELECT * FROM messages WHERE message_id = ?", (msg_id,)
    )


async def get_messages(from_user: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """获取消息列表 (gateway 兼容签名)"""
    if from_user:
        return await db_client.fetch_all(
            "SELECT * FROM messages WHERE from_user = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (from_user, limit, offset),
        )
    return await db_client.fetch_all(
        "SELECT * FROM messages ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
    )


async def get_messages_by_session(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """获取指定会话的所有消息"""
    return await db_client.fetch_all(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
        (session_id, limit),
    )


async def delete_session(session_id: str) -> int:
    """删除会话"""
    return await db_client.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


async def save_message(payload: Dict[str, Any]) -> int:
    """保存消息到数据库"""
    sql = """
        INSERT INTO messages (message_id, session_id, from_user, msg_type, content, created_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """
    return await db_client.execute(sql, (
        payload.get("msg_id", ""),
        payload.get("session_id", ""),
        payload.get("from_user", ""),
        payload.get("msg_type", ""),
        payload.get("content", ""),
    ))


async def create_or_update_session(user_id: str) -> int:
    """创建或更新会话"""
    sql = """
        INSERT INTO sessions (session_id, user_id, agent_name, stage, message_count, created_at, updated_at)
        VALUES (?, ?, 'router', 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(session_id) DO UPDATE SET
            message_count = message_count + 1,
            updated_at = CURRENT_TIMESTAMP
    """
    import uuid
    session_id = str(uuid.uuid4())
    return await db_client.execute(sql, (session_id, user_id))


async def update_sla_response(msg_id: str) -> int:
    """更新 SLA 响应时间"""
    return await db_client.execute(
        "UPDATE messages SET sla_response_at = CURRENT_TIMESTAMP WHERE message_id = ?",
        (msg_id,),
    )


async def save_confirmed_event(
    push_id: str,
    from_user: str,
    raw_text: str,
    event_type: str,
    severity: str,
    context_trigger_data: Dict[str, Any],
    venue_id: Optional[str] = None,
) -> str:
    """
    将员工确认的事件写入 confirmed_events 表（记忆库核心写入）

    同时写入向量库（通过 vector_client）。

    Returns:
        event_id: 生成的事件ID
    """
    import uuid
    from ..tools.llm_wrapper import sanitize_llm_output

    event_id = str(uuid.uuid4())
    vector_doc_id = f"evt_{event_id}"

    # 消毒 event_data
    cleaned, warns = sanitize_llm_output(
        {"event_type": event_type, "raw_text": raw_text, "severity": severity},
        "push_event",
    )
    if cleaned:
        event_type = cleaned.get("event_type", event_type)
        raw_text = cleaned.get("raw_text", raw_text)
        severity = cleaned.get("severity", "P3")

    # 1. 写入结构化表
    await db_client.execute(
        """
        INSERT INTO confirmed_events (
            event_id, push_id, from_user, raw_text, event_type, severity,
            context_trigger_data, memory_content, vector_doc_id, confirmed_at, venue_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            push_id,
            from_user,
            raw_text,
            event_type,
            severity,
            json.dumps(context_trigger_data, ensure_ascii=False),
            _build_memory_content(raw_text, event_type, severity),
            vector_doc_id,
            time.time(),
            venue_id or "",
        ),
    )

    # 2. 写入向量库（异步，不阻塞主流程）
    try:
        from .vector_store import get_vector_client

        vc = get_vector_client()
        if vc is None:
            logger.warning("[PushLogger] 向量库未初始化，跳过向量写入")
            return

        metadata = {
            "event_type": event_type,
            "severity": severity,
            "from_user": from_user,
            "event_id": event_id,
            "venue_id": venue_id or "",
        }
        vc.upsert_experience(
            content=_build_memory_content(raw_text, event_type, severity),
            metadata=metadata,
            doc_id=vector_doc_id,
        )
    except Exception as e:
        logger.error(f"[PushLogger] 向量库写入失败: {e}")

    logger.info(f"[PushLogger] 事件写入记忆库: event_id={event_id}, type={event_type}")
    return event_id


def _build_memory_content(raw_text: str, event_type: str, severity: str) -> str:
    """构建记忆库存储内容"""
    return f"[{severity}] {event_type}事件：{raw_text}"
