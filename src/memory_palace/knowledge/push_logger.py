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
) -> str:
    """
    写入推送日志

    Returns:
        push_id: 生成的推送日志ID
    """
    push_id = str(uuid.uuid4())[:12]

    await db_client.execute(
        """
        INSERT INTO push_logs (
            push_id, msg_id, from_user, raw_text, event_type, severity,
            stage1_triggered, hit_keywords, stage2_triggered, llm_confidence,
            pushed_at, adoption_status, trace_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            push_id,
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
        ),
    )

    logger.info(f"[PushLogger] 写入推送日志: push_id={push_id}, event_type={event_type}")
    return push_id


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
