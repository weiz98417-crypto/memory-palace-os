"""Project advice-run state into incident activities and SSE events."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Awaitable, Callable

from ..core.event_activities import append_event_activity

Publisher = Callable[[dict[str, Any]], Awaitable[None]]

_EVENT_NAME = {
    "ADVICE_FAILED": "ADVICE_FAILED",
    "ADVICE_READY": "ADVICE_READY",
    "ADVICE_DECIDED": "ADVICE_READY",
    "ADVICE_SUPERSEDED": "ADVICE_READY",
}


class DatabaseAdviceSink:
    """Writes the advice activity and the derived situation event.

    This is deliberately database-only: the Hatchet worker runs in its own process and
    must publish the same evidence the API process would, without constructing the whole
    scenic operations module. Both entry points share this one implementation so the
    activity/SSE semantics cannot drift.
    """

    def __init__(self, database: Any, *, publisher: Publisher | None = None) -> None:
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._publisher = publisher

    async def finalize(
        self,
        *,
        run: Any,
        state: str,
        activity_type: str,
        payload: dict[str, Any],
        system_context: str | None = None,
    ) -> None:
        await self.project(
            venue_id=run.venue_id,
            incident_id=run.incident_id,
            run_id=run.run_id,
            state=state,
            activity_type=activity_type,
            payload=payload,
            system_context=system_context,
        )

    async def project(
        self,
        *,
        venue_id: str,
        incident_id: str,
        run_id: str,
        state: str,
        activity_type: str,
        payload: dict[str, Any],
        system_context: str | None = None,
    ) -> dict[str, Any]:
        incident = await self._database.fetch_one(
            "SELECT * FROM scenic_incidents WHERE venue_id = ? AND incident_id = ?",
            (venue_id, incident_id),
        )
        if incident is None:
            raise RuntimeError("advice run incident was not found")
        body = dict(payload)
        body["advice_run_id"] = run_id
        body["incident_id"] = incident_id
        body["state"] = state
        if system_context:
            body["system_context"] = system_context
        await append_event_activity(
            self._database,
            venue_id=venue_id,
            event_id=str(incident["event_id"]),
            activity_type=activity_type,
            trace_id=str(body.get("trace_id") or ""),
            payload=body,
            idempotency_key=f"advice:{run_id}:{activity_type}:{state}",
        )
        event = await self.record_event(
            venue_id=venue_id,
            run_id=str(incident["run_id"]),
            incident_id=incident_id,
            event_name=_EVENT_NAME.get(activity_type, "ADVICE_PENDING"),
            payload={
                "advice_run_id": run_id,
                "state": state,
                "activity_type": activity_type,
                "system_context": system_context,
            },
        )
        return event

    async def record_event(
        self,
        *,
        venue_id: str,
        run_id: str,
        incident_id: str,
        event_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event_id = uuid.uuid4().hex
        recorded_at = time.time()
        await self._database.execute(
            """
            INSERT INTO scenic_situation_events (
                event_id, venue_id, run_id, event_type, resource_type,
                resource_id, payload_json, simulated_at, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                venue_id,
                run_id,
                event_name,
                "scenic_incident",
                incident_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                None,
                recorded_at,
            ),
        )
        row = await self._database.fetch_one(
            "SELECT * FROM scenic_situation_events WHERE event_id = ?", (event_id,)
        )
        event = dict(row or {})
        if self._publisher is not None:
            await self._publisher(event)
        return event


__all__ = ["DatabaseAdviceSink"]
