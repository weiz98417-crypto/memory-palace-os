from __future__ import annotations

from typing import Any, Optional

from .event_activities import append_event_activity


def _task_payload(task: Any) -> dict[str, Any]:
    if hasattr(task, "to_dict"):
        return task.to_dict()
    return dict(task)


async def append_task_activity(
    database,
    *,
    venue_id: str,
    task: Any,
    activity_type: str,
    created_by: Optional[str],
    trace_id: str,
    summary: str,
    extra_payload: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    task_data = _task_payload(task)
    event_id = task_data.get("event_id")
    if not event_id:
        return None
    payload = {
        "summary": summary,
        "task_id": task_data.get("id"),
        "task_business_id": task_data.get("business_id"),
        "description": task_data.get("description"),
        "status": task_data.get("status"),
        "assigned_user_id": task_data.get("assigned_user_id"),
        "assigned_agent": task_data.get("assigned_agent"),
        "attempts": task_data.get("attempts"),
        "max_attempts": task_data.get("max_attempts"),
    }
    if extra_payload:
        payload.update(extra_payload)
    return await append_event_activity(
        database,
        venue_id=venue_id,
        event_id=str(event_id),
        session_id=task_data.get("session_id"),
        trace_id=trace_id,
        activity_type=activity_type,
        created_by=created_by,
        payload=payload,
        idempotency_key=(
            f"task:{task_data.get('id')}:{activity_type.lower()}:{trace_id}"
        ),
    )
