"""
推送日志写入模块 (Push Logger)

负责记录每次 ContextTrigger 推送的完整生命周期：
- push_id: 推送唯一ID
- msg_id: 对应的原始消息ID
- from_user: 发送者
- raw_text: 原始消息
- event_type / severity: 事件分类
- stage1 / stage2 结果
- pushed_at: 推送时间
- confirmed_at / adoption_status: 确认状态

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import json
import time
import uuid
from typing import Any, Dict, Optional

from loguru import logger

from ..core.sensitive_output import sanitize_public_value
from .db_client import db_client


async def write_push_log(
    msg_id: str,
    from_user: str,
    raw_text: str,
    event_type: str,
    severity: str,
    stage1_triggered: bool,
    hit_keywords: list,
    stage2_triggered: Optional[bool],
    llm_confidence: Optional[float],
    trace_id: str,
    venue_id: str = "",
    database: Any = None,
    channel: str = "legacy",
    recipient: Optional[str] = None,
    delivery_status: str = "RECORDED",
    delivery_error: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> str:
    """
    写入推送日志

    Returns:
        push_id: 生成的推送日志ID
    """
    push_id = str(uuid.uuid4())[:12]
    target_db = database or db_client

    inserted = await target_db.execute(
        """
        INSERT INTO push_logs (
            push_id, venue_id, msg_id, from_user, raw_text, event_type, severity,
            stage1_triggered, hit_keywords, stage2_triggered, llm_confidence,
            pushed_at, adoption_status, trace_id, channel, recipient,
            delivery_status, delivery_error, idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(venue_id, channel, idempotency_key) DO NOTHING
        """,
        (
            push_id,
            venue_id,
            msg_id,
            from_user,
            raw_text,
            event_type,
            severity,
            stage1_triggered,
            json.dumps(hit_keywords, ensure_ascii=False),
            stage2_triggered,
            llm_confidence,
            time.time(),
            "pending",
            trace_id,
            channel,
            recipient,
            delivery_status,
            delivery_error,
            idempotency_key,
        ),
    )

    if inserted == 0 and idempotency_key is not None:
        existing = await target_db.fetch_one(
            """
            SELECT push_id FROM push_logs
            WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
            """,
            (venue_id, channel, idempotency_key),
        )
        if existing:
            return existing["push_id"]
        raise RuntimeError("idempotent push insert was not persisted")

    logger.info(f"[PushLogger] 写入推送日志: push_id={push_id}, event_type={event_type}")
    return push_id


async def record_reply_delivery(
    *,
    message_id: str,
    trace_id: str,
    venue_id: str,
    user_id: str,
    channel: str,
    recipient: Optional[str],
    reply_text: str,
    delivery_status: str,
    delivery_error: Optional[str] = None,
    database: Any = None,
) -> str:
    """Create or update the single delivery ledger row for an assistant reply."""
    target_db = database or db_client
    normalized_channel = f"{channel.strip().upper()}_REPLY"
    idempotency_key = f"assistant-reply:{message_id}"
    sanitized_error = sanitize_public_value(delivery_error)
    if sanitized_error is not None and not isinstance(sanitized_error, str):
        sanitized_error = str(sanitized_error)
    push_id = await write_push_log(
        msg_id=message_id,
        from_user=user_id,
        raw_text=reply_text,
        event_type="助手回复",
        severity="INFO",
        stage1_triggered=False,
        hit_keywords=[],
        stage2_triggered=None,
        llm_confidence=None,
        trace_id=trace_id,
        venue_id=venue_id,
        database=target_db,
        channel=normalized_channel,
        recipient=recipient,
        delivery_status=delivery_status,
        delivery_error=sanitized_error,
        idempotency_key=idempotency_key,
    )
    normalized_status = delivery_status.strip().upper()
    if normalized_status == "DELIVERED":
        await target_db.execute(
            """
            UPDATE push_logs
            SET trace_id = ?, recipient = ?, raw_text = ?, delivery_status = ?,
                delivery_error = ?, adoption_status = 'not_applicable', pushed_at = ?,
                delivery_claim_token = NULL, delivery_claimed_at = NULL
            WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
            """,
            (
                trace_id,
                recipient,
                reply_text,
                normalized_status,
                sanitized_error,
                time.time(),
                venue_id,
                normalized_channel,
                idempotency_key,
            ),
        )
    else:
        await target_db.execute(
            """
            UPDATE push_logs
            SET trace_id = ?, recipient = ?, raw_text = ?, delivery_status = ?,
                delivery_error = ?, adoption_status = 'not_applicable', pushed_at = ?
            WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
              AND delivery_status NOT IN ('DELIVERED', 'SENDING')
            """,
            (
                trace_id,
                recipient,
                reply_text,
                normalized_status,
                sanitized_error,
                time.time(),
                venue_id,
                normalized_channel,
                idempotency_key,
            ),
        )
    return push_id


async def claim_reply_delivery(
    *,
    message_id: str,
    trace_id: str,
    venue_id: str,
    user_id: str,
    channel: str,
    recipient: Optional[str],
    reply_text: str,
    allow_manual_reclaim: bool = False,
    database: Any = None,
) -> Dict[str, Any]:
    """Atomically acquire the durable right to perform one external reply send."""
    target_db = database or db_client
    normalized_channel = f"{channel.strip().upper()}_REPLY"
    idempotency_key = f"assistant-reply:{message_id}"
    push_id = await write_push_log(
        msg_id=message_id,
        from_user=user_id,
        raw_text=reply_text,
        event_type="助手回复",
        severity="INFO",
        stage1_triggered=False,
        hit_keywords=[],
        stage2_triggered=None,
        llm_confidence=None,
        trace_id=trace_id,
        venue_id=venue_id,
        database=target_db,
        channel=normalized_channel,
        recipient=recipient,
        delivery_status="PENDING",
        idempotency_key=idempotency_key,
    )
    claim_token = uuid.uuid4().hex
    claimed_at = time.time()
    acquired = await target_db.execute(
        """
        UPDATE push_logs
        SET trace_id = ?, recipient = ?, raw_text = ?, delivery_status = 'SENDING',
            delivery_error = NULL, adoption_status = 'not_applicable', pushed_at = ?,
            delivery_claim_token = ?, delivery_claimed_at = ?
        WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
          AND (
              delivery_status IN ('PENDING', 'FAILED', 'CONFIGURATION_REQUIRED', 'RECORDED')
              OR (? = 1 AND delivery_status = 'SENDING')
          )
        """,
        (
            trace_id,
            recipient,
            reply_text,
            claimed_at,
            claim_token,
            claimed_at,
            venue_id,
            normalized_channel,
            idempotency_key,
            1 if allow_manual_reclaim else 0,
        ),
    )
    row = await target_db.fetch_one(
        """
        SELECT push_id, delivery_status
        FROM push_logs
        WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
        """,
        (venue_id, normalized_channel, idempotency_key),
    )
    if not row:
        raise RuntimeError("reply delivery claim was not persisted")
    return {
        "push_id": row.get("push_id") or push_id,
        "acquired": acquired == 1,
        "claim_token": claim_token if acquired == 1 else None,
        "delivery_status": str(row.get("delivery_status") or "PENDING").upper(),
    }


async def complete_reply_delivery(
    *,
    message_id: str,
    trace_id: str,
    venue_id: str,
    channel: str,
    recipient: Optional[str],
    reply_text: str,
    claim_token: str,
    delivery_status: str,
    delivery_error: Optional[str] = None,
    database: Any = None,
) -> bool:
    """Persist a delivery outcome only for the worker that owns the send claim."""
    normalized_status = delivery_status.strip().upper()
    if normalized_status not in {"DELIVERED", "FAILED"}:
        raise ValueError(f"Unsupported claimed delivery status: {delivery_status}")
    target_db = database or db_client
    normalized_channel = f"{channel.strip().upper()}_REPLY"
    idempotency_key = f"assistant-reply:{message_id}"
    sanitized_error = sanitize_public_value(delivery_error)
    if sanitized_error is not None and not isinstance(sanitized_error, str):
        sanitized_error = str(sanitized_error)
    updated = await target_db.execute(
        """
        UPDATE push_logs
        SET trace_id = ?, recipient = ?, raw_text = ?, delivery_status = ?,
            delivery_error = ?, adoption_status = 'not_applicable', pushed_at = ?,
            delivery_claim_token = NULL, delivery_claimed_at = NULL
        WHERE venue_id = ? AND channel = ? AND idempotency_key = ?
          AND delivery_status = 'SENDING' AND delivery_claim_token = ?
        """,
        (
            trace_id,
            recipient,
            reply_text,
            normalized_status,
            sanitized_error,
            time.time(),
            venue_id,
            normalized_channel,
            idempotency_key,
            claim_token,
        ),
    )
    return updated == 1


async def update_push_confirm(
    push_id: str,
    adoption_status: str,
    confirmed_by: str,
    confirmed_notes: Optional[str] = None,
) -> int:
    """
    更新推送确认状态

    Args:
        push_id: 推送日志ID
        adoption_status: 采纳状态 ('adopted' | 'modified' | 'rejected')
        confirmed_by: 确认人
        confirmed_notes: 补充说明（可选）
    """
    rowcount = await db_client.execute(
        """
        UPDATE push_logs
        SET confirmed_at = ?, adoption_status = ?, confirmed_by = ?, confirmed_notes = ?
        WHERE push_id = ?
        """,
        (time.time(), adoption_status, confirmed_by, confirmed_notes or "", push_id),
    )

    logger.info(
        f"[PushLogger] 更新推送确认: push_id={push_id}, status={adoption_status}"
    )
    return rowcount


async def get_push_log(push_id: str) -> Optional[Dict[str, Any]]:
    """根据 push_id 获取推送日志"""
    return await db_client.fetch_one(
        "SELECT * FROM push_logs WHERE push_id = ?", (push_id,)
    )


async def get_recent_push_logs(
    from_user: Optional[str] = None,
    limit: int = 50,
    adoption_status: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """
    获取最近的推送日志

    Args:
        from_user: 按发送者筛选
        limit: 返回条数
        adoption_status: 按采纳状态筛选
    """
    sql = "SELECT * FROM push_logs WHERE 1=1"
    params = []

    if from_user:
        sql += " AND from_user = ?"
        params.append(from_user)

    if adoption_status:
        sql += " AND adoption_status = ?"
        params.append(adoption_status)

    sql += " ORDER BY pushed_at DESC LIMIT ?"
    params.append(limit)

    return await db_client.fetch_all(sql, tuple(params))
