import json
import time
import uuid
from typing import Any, Optional


async def append_event_activity(
    database,
    *,
    venue_id: str,
    event_id: str,
    activity_type: str,
    created_by: Optional[str] = None,
    session_id: Optional[str] = None,
    message_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
    created_at: Optional[float] = None,
) -> dict[str, Any]:
    normalized_venue_id = venue_id or ""
    normalized_trace_id = trace_id or ""
    normalized_created_at = created_at or time.time()
    if idempotency_key:
        activity_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                ":".join(
                    (
                        "memory-palace-event-activity",
                        normalized_venue_id,
                        event_id,
                        idempotency_key,
                    )
                ),
            )
        )
    else:
        activity_id = str(uuid.uuid4())

    await database.execute(
        """
        INSERT INTO event_activities (
            id, venue_id, event_id, session_id, message_id, trace_id,
            activity_type, payload_json, idempotency_key, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            activity_id,
            normalized_venue_id,
            event_id,
            session_id,
            message_id,
            normalized_trace_id,
            activity_type,
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            idempotency_key,
            created_by,
            normalized_created_at,
        ),
    )

    if idempotency_key and hasattr(database, "fetch_one"):
        existing = await database.fetch_one(
            """
            SELECT * FROM event_activities
            WHERE venue_id = ? AND event_id = ? AND idempotency_key = ?
            """,
            (normalized_venue_id, event_id, idempotency_key),
        )
        if existing:
            return existing

    return {
        "id": activity_id,
        "venue_id": normalized_venue_id,
        "event_id": event_id,
        "session_id": session_id,
        "message_id": message_id,
        "trace_id": normalized_trace_id,
        "activity_type": activity_type,
        "payload_json": json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
        "idempotency_key": idempotency_key,
        "created_by": created_by,
        "created_at": normalized_created_at,
    }
