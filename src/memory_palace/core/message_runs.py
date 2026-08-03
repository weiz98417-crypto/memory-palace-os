"""Persistent state for asynchronous message processing runs."""

import json
import time
from typing import Any, Optional

from .sensitive_output import sanitize_public_value


DELIVERY_STATUSES = {
    "PENDING",
    "SENDING",
    "DELIVERED",
    "FAILED",
    "CONFIGURATION_REQUIRED",
    "PERSISTED",
}


class MessageRunRepository:
    """Store and retrieve traceable message processing state."""

    def __init__(self, db_client: Any):
        self._db = db_client

    async def create(
        self,
        *,
        message_id: str,
        trace_id: str,
        session_id: str,
        user_id: str,
        venue_id: str,
        content: str,
    ) -> None:
        now = time.time()
        await self._db.execute(
            """
            INSERT INTO message_runs (
                message_id, trace_id, session_id, user_id, venue_id, content,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, trace_id, session_id, user_id, venue_id, content, "QUEUED", now, now),
        )

    async def get(
        self,
        message_id: str,
        venue_id: Optional[str] = None,
        *,
        user_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        if venue_id and user_id:
            row = await self._db.fetch_one(
                """
                SELECT * FROM message_runs
                WHERE message_id = ? AND venue_id = ? AND user_id = ?
                """,
                (message_id, venue_id, user_id),
            )
        elif venue_id:
            row = await self._db.fetch_one(
                "SELECT * FROM message_runs WHERE message_id = ? AND venue_id = ?",
                (message_id, venue_id),
            )
        else:
            row = await self._db.fetch_one(
                "SELECT * FROM message_runs WHERE message_id = ?",
                (message_id,),
            )
        if not row:
            return None

        result_json = row.pop("result_json", None)
        try:
            row["result"] = json.loads(result_json) if result_json else None
        except (TypeError, json.JSONDecodeError):
            row["result"] = None
        row["attempt_count"] = int(row.get("attempt_count") or 0)
        row["max_attempts"] = int(row.get("max_attempts") or 4)
        row["manual_retry_count"] = int(row.get("manual_retry_count") or 0)
        row["retryable"] = row.get("status") in {
            "RETRY_REQUIRED",
            "DEAD_LETTERED",
        }
        return row

    async def mark_failed(
        self,
        message_id: str,
        error: str,
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        now = time.time()
        if result is not None:
            route = result.get("route") or {}
            await self._db.execute(
                """
                UPDATE message_runs
                SET status = ?, target_agent = ?, reply_text = ?, result_json = ?,
                    error = ?, updated_at = ?, processed_at = ?
                WHERE message_id = ?
                """,
                (
                    "FAILED",
                    route.get("target_agent"),
                    result.get("reply_text"),
                    json.dumps(result, ensure_ascii=False, default=_json_default),
                    error,
                    now,
                    now,
                    message_id,
                ),
            )
            return
        await self._db.execute(
            """
            UPDATE message_runs
            SET status = ?, error = ?, updated_at = ?, processed_at = ?
            WHERE message_id = ?
            """,
            ("FAILED", error, now, now, message_id),
        )

    async def mark_processing(self, message_id: str, *, recovering: bool = False) -> None:
        await self._db.execute(
            """
            UPDATE message_runs
            SET status = ?, attempt_count = attempt_count + 1,
                error = NULL, processed_at = NULL, updated_at = ?
            WHERE message_id = ?
            """,
            ("RECOVERING" if recovering else "PROCESSING", time.time(), message_id),
        )

    async def claim_processing(
        self,
        message_id: str,
        *,
        recovering: bool = False,
        expected_status: str,
    ) -> bool:
        normalized_status = str(expected_status or "").upper()
        claimable_statuses = {"QUEUED", "RETRYING"}
        if recovering:
            claimable_statuses.update({"PROCESSING", "RECOVERING"})
        if normalized_status not in claimable_statuses:
            return False
        affected_rows = await self._db.execute(
            """
            UPDATE message_runs
            SET status = ?, attempt_count = attempt_count + 1,
                error = NULL, processed_at = NULL, updated_at = ?
            WHERE message_id = ?
              AND status = ?
            """,
            (
                "RECOVERING" if recovering else "PROCESSING",
                time.time(),
                message_id,
                normalized_status,
            ),
        )
        return affected_rows == 1

    async def save_result(self, message_id: str, result: dict[str, Any]) -> None:
        route = result.get("route") or {}
        await self._db.execute(
            """
            UPDATE message_runs
            SET target_agent = ?, reply_text = ?, result_json = ?, updated_at = ?
            WHERE message_id = ?
            """,
            (
                route.get("target_agent"),
                result.get("reply_text"),
                json.dumps(result, ensure_ascii=False, default=_json_default),
                time.time(),
                message_id,
            ),
        )

    async def mark_delivery(
        self,
        message_id: str,
        status: str,
        *,
        error: Optional[str] = None,
        delivered_at: Optional[float] = None,
    ) -> None:
        normalized_status = status.strip().upper()
        if normalized_status not in DELIVERY_STATUSES:
            raise ValueError(f"Unsupported delivery status: {status}")
        if normalized_status in {"DELIVERED", "PERSISTED"} and delivered_at is None:
            delivered_at = time.time()
        if normalized_status not in {"DELIVERED", "PERSISTED"}:
            delivered_at = None
        sanitized_error = sanitize_public_value(error)
        if sanitized_error is not None and not isinstance(sanitized_error, str):
            sanitized_error = str(sanitized_error)
        await self._db.execute(
            """
            UPDATE message_runs
            SET delivery_status = ?, delivery_error = ?, delivered_at = ?, updated_at = ?
            WHERE message_id = ?
              AND (delivery_status != 'DELIVERED' OR ? = 'DELIVERED')
            """,
            (
                normalized_status,
                sanitized_error,
                delivered_at,
                time.time(),
                message_id,
                normalized_status,
            ),
        )

    async def mark_retrying(
        self,
        message_id: str,
        error: str,
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        await self._mark_recoverable_failure(
            message_id,
            status="RETRYING",
            error=error,
            result=result,
            dead_letter_id=None,
            processed_at=None,
        )

    async def mark_retry_required(
        self,
        message_id: str,
        error: str,
        *,
        dead_letter_id: Optional[str] = None,
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        await self._mark_recoverable_failure(
            message_id,
            status="RETRY_REQUIRED",
            error=error,
            result=result,
            dead_letter_id=dead_letter_id,
            processed_at=time.time(),
        )

    async def mark_manual_retry(self, message_id: str) -> None:
        await self._db.execute(
            """
            UPDATE message_runs
            SET status = 'RETRYING', manual_retry_count = manual_retry_count + 1,
                dead_letter_id = NULL, error = NULL, processed_at = NULL,
                updated_at = ?
            WHERE message_id = ?
            """,
            (time.time(), message_id),
        )

    async def _mark_recoverable_failure(
        self,
        message_id: str,
        *,
        status: str,
        error: str,
        result: Optional[dict[str, Any]],
        dead_letter_id: Optional[str],
        processed_at: Optional[float],
    ) -> None:
        route = (result or {}).get("route") or {}
        result_json = (
            json.dumps(result, ensure_ascii=False, default=_json_default)
            if result is not None
            else None
        )
        await self._db.execute(
            """
            UPDATE message_runs
            SET status = ?, target_agent = COALESCE(?, target_agent),
                reply_text = COALESCE(?, reply_text),
                result_json = COALESCE(?, result_json), error = ?,
                dead_letter_id = ?, updated_at = ?, processed_at = ?
            WHERE message_id = ?
              AND status != 'COMPLETED'
              AND delivery_status != 'DELIVERED'
            """,
            (
                status,
                route.get("target_agent"),
                (result or {}).get("reply_text"),
                result_json,
                error,
                dead_letter_id,
                time.time(),
                processed_at,
                message_id,
            ),
        )

    async def mark_completed(self, message_id: str, result: dict[str, Any]) -> None:
        now = time.time()
        route = result.get("route") or {}
        await self._db.execute(
            """
            UPDATE message_runs
            SET status = ?, target_agent = ?, reply_text = ?, result_json = ?,
                error = NULL, dead_letter_id = NULL, updated_at = ?, processed_at = ?
            WHERE message_id = ?
            """,
            (
                "COMPLETED",
                route.get("target_agent"),
                result.get("reply_text"),
                json.dumps(result, ensure_ascii=False, default=_json_default),
                now,
                now,
                message_id,
            ),
        )


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
