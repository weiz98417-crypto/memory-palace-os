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
    normalized_created_at = await _monotonic_event_timestamp(
        database,
        venue_id=normalized_venue_id,
        event_id=event_id,
        candidate=normalized_created_at,
    )
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

    if hasattr(database, "fetch_one"):
        if idempotency_key:
            existing = await database.fetch_one(
                """
                SELECT * FROM event_activities
                WHERE venue_id = ? AND event_id = ? AND idempotency_key = ?
                """,
                (normalized_venue_id, event_id, idempotency_key),
            )
        else:
            existing = await database.fetch_one(
                """
                SELECT * FROM event_activities
                WHERE venue_id = ? AND event_id = ? AND id = ?
                """,
                (normalized_venue_id, event_id, activity_id),
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

async def _monotonic_event_timestamp(
    database,
    *,
    venue_id: str,
    event_id: str,
    candidate: float,
    epsilon: float = 1e-6,
) -> float:
    """Keep one event's activity timestamps strictly increasing.

    Two actions in the same millisecond (for example block then unblock) would
    otherwise share a ``created_at`` value; because activity ids are UUIDs the
    dossier could then render them out of order. A monotonic timestamp keeps the
    audit timeline faithful to the order in which the business actually acted.
    """

    fetch_one = getattr(database, "fetch_one", None)
    if not callable(fetch_one):
        return candidate

    current = float(candidate)
    for _ in range(8):
        latest = await fetch_one(
            """
            SELECT MAX(created_at) AS latest_at
            FROM event_activities
            WHERE venue_id = ? AND event_id = ?
            """,
            (venue_id, event_id),
        )
        latest_at = (latest or {}).get("latest_at") if latest else None
        if latest_at is None or float(latest_at) < current:
            return current
        current = float(latest_at) + epsilon
    return current
