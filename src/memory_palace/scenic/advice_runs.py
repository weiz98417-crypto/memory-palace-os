"""Async advice runs: state machine, queue, and worker.

`scenic_commands` stays the durable fact for a run (ADR-0018); Redis Streams only
carries the work item and the in-process queue is the single-node equivalent. State
transitions are compare-and-swap so a late model result can never resurrect a run that
a human already superseded.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Protocol

from ..incident.contracts import IncidentCommandRequest

AdviceState = Literal["PENDING", "RUNNING", "READY", "FAILED", "SUPERSEDED"]
TERMINAL_STATES = frozenset({"READY", "FAILED", "SUPERSEDED"})
ADVICE_COMMAND_TYPE = "GENERATE_ADVICE"

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"RUNNING", "FAILED", "SUPERSEDED"}),
    "RUNNING": frozenset({"READY", "FAILED", "SUPERSEDED"}),
    "READY": frozenset(),
    "FAILED": frozenset(),
    "SUPERSEDED": frozenset(),
}


def advice_run_id(incident_id: str, *, step: str, attempt: int) -> str:
    """Stable run id, so a retried enqueue resolves to the same run."""

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"memory-palace-advice-run:{incident_id}:{step}:{attempt}",
        )
    )


def advice_idempotency_key(incident_id: str, *, step: str, attempt: int) -> str:
    return f"advice:{incident_id}:{step}:{attempt}"


def _request_hash(request: IncidentCommandRequest) -> str:
    return hashlib.sha256(
        request.model_dump_json(exclude_none=False).encode("utf-8")
    ).hexdigest()


class AdviceRunConflict(RuntimeError):
    """Raised when an idempotency key is reused for different advice inputs."""


@dataclass(frozen=True)
class AdviceRun:
    run_id: str
    venue_id: str
    incident_id: str
    step: str
    attempt: int
    state: str
    request: IncidentCommandRequest | None
    result: dict[str, Any] | None
    error_type: str | None
    error_message: str | None
    created_at: float
    updated_at: float


class AdviceRunRepository:
    """Durable advice-run state over the existing `scenic_commands` table."""

    def __init__(self, database: Any, *, clock: Callable[[], float] | None = None) -> None:
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._clock = clock or time.time

    def _now(self) -> float:
        return float(self._clock())

    async def create_or_get(
        self,
        *,
        venue_id: str,
        incident_id: str,
        step: str,
        attempt: int,
        request: IncidentCommandRequest,
    ) -> tuple[AdviceRun, bool]:
        key = advice_idempotency_key(incident_id, step=step, attempt=attempt)
        run_id = advice_run_id(incident_id, step=step, attempt=attempt)
        request_payload = request.model_dump_json()
        digest = _request_hash(request)
        now = self._now()
        inserted = await self._database.execute(
            """
            INSERT INTO scenic_commands (
                id, venue_id, command_type, idempotency_key, request_hash,
                status, request_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            ON CONFLICT (venue_id, idempotency_key) DO NOTHING
            """,
            (run_id, venue_id, ADVICE_COMMAND_TYPE, key, digest, request_payload, now, now),
        )
        row = await self._database.fetch_one(
            "SELECT * FROM scenic_commands WHERE venue_id = ? AND idempotency_key = ?",
            (venue_id, key),
        )
        if row is None:  # pragma: no cover - defensive
            raise AdviceRunConflict("advice run could not be created")
        if row["request_hash"] != digest:
            raise AdviceRunConflict(
                "advice idempotency key was already used with different inputs"
            )
        run = self._to_run(row)
        # `created` means "this call inserted the row"; it is the signal to enqueue.
        # A run that is already queued stays PENDING, so it must not be enqueued twice.
        return run, int(inserted or 0) == 1

    async def get(self, *, venue_id: str, run_id: str) -> AdviceRun | None:
        row = await self._database.fetch_one(
            "SELECT * FROM scenic_commands WHERE venue_id = ? AND id = ?",
            (venue_id, run_id),
        )
        return self._to_run(row) if row else None

    async def list_for_incident(
        self, *, venue_id: str, incident_id: str
    ) -> list[AdviceRun]:
        rows = await self._database.fetch_all(
            """
            SELECT * FROM scenic_commands
            WHERE venue_id = ? AND command_type = ? AND idempotency_key LIKE ?
            ORDER BY created_at
            """,
            (venue_id, ADVICE_COMMAND_TYPE, f"advice:{incident_id}:%"),
        )
        return [self._to_run(row) for row in rows or []]

    async def transition(
        self,
        *,
        venue_id: str,
        run_id: str,
        expected: str | tuple[str, ...],
        new_state: str,
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
        system_context: str | None = None,
    ) -> bool:
        expected_states = (expected,) if isinstance(expected, str) else tuple(expected)
        for state in expected_states:
            if new_state not in _ALLOWED_TRANSITIONS.get(state, frozenset()):
                raise AdviceRunConflict(
                    f"illegal advice transition {state} -> {new_state}"
                )
        if new_state in {"READY", "FAILED"}:
            payload_state = new_state
        else:
            payload_state = new_state
        now = self._now()
        response_payload = None
        if response is not None:
            body = dict(response)
            body.setdefault("state", payload_state)
            if system_context:
                body.setdefault("system_context", system_context)
            response_payload = json.dumps(body, ensure_ascii=False, sort_keys=True)
        placeholders = ",".join("?" for _ in expected_states)
        return (
            await self._database.execute(
                f"""
                UPDATE scenic_commands
                SET status = ?, response_json = COALESCE(?, response_json),
                    error_type = ?, error_message = ?, updated_at = ?
                WHERE venue_id = ? AND id = ? AND status IN ({placeholders})
                """,
                (
                    new_state,
                    response_payload,
                    type(error).__name__ if error else None,
                    str(error)[:500] if error else None,
                    now,
                    venue_id,
                    run_id,
                    *expected_states,
                ),
            )
            == 1
        )

    async def record_late_result(
        self, *, venue_id: str, run_id: str, response: dict[str, Any]
    ) -> None:
        """Keep a late model result without resurrecting a superseded run."""

        run = await self.get(venue_id=venue_id, run_id=run_id)
        if run is None or run.state != "SUPERSEDED":
            return
        body = dict(run.result or {})
        body["late_result"] = response
        body["state"] = "SUPERSEDED"
        await self._database.execute(
            """
            UPDATE scenic_commands SET response_json = ?, updated_at = ?
            WHERE venue_id = ? AND id = ? AND status = 'SUPERSEDED'
            """,
            (
                json.dumps(body, ensure_ascii=False, sort_keys=True),
                self._now(),
                venue_id,
                run_id,
            ),
        )

    def _to_run(self, row: Any) -> AdviceRun:
        request_payload = row.get("request_json") if hasattr(row, "get") else None
        request = (
            IncidentCommandRequest.model_validate_json(request_payload)
            if request_payload
            else None
        )
        key = str(row.get("idempotency_key") or "")
        parts = key.split(":")
        incident_id = parts[1] if len(parts) > 1 else ""
        step = parts[2] if len(parts) > 2 else ""
        try:
            attempt = int(parts[3]) if len(parts) > 3 else 1
        except ValueError:
            attempt = 1
        response = row.get("response_json") if hasattr(row, "get") else None
        return AdviceRun(
            run_id=str(row["id"]),
            venue_id=str(row["venue_id"]),
            incident_id=incident_id,
            step=step,
            attempt=attempt,
            state=str(row["status"]),
            request=request,
            result=json.loads(response) if response else None,
            error_type=row.get("error_type"),
            error_message=row.get("error_message"),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


class AdviceQueue(Protocol):
    backend_name: str

    async def enqueue(self, message: dict[str, Any]) -> None: ...

    async def claim(self) -> dict[str, Any] | None: ...

    async def ack(self, message: dict[str, Any]) -> None: ...


class InMemoryAdviceQueue:
    """Single-process queue used by the native stack and tests."""

    backend_name = "in_memory"

    def __init__(self, *, max_retries: int = 3) -> None:
        self._items: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._attempts: dict[str, int] = {}
        self._max_retries = max_retries

    async def enqueue(self, message: dict[str, Any]) -> None:
        await self._items.put(dict(message))

    async def claim(self) -> dict[str, Any] | None:
        try:
            return self._items.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def ack(self, message: dict[str, Any]) -> None:
        key = str(message.get("advice_run_id") or "")
        self._attempts.pop(key, None)


@dataclass(frozen=True)
class AdviceFinalized:
    run: AdviceRun
    state: str


class AdviceSink(Protocol):
    """Side effects after a run reaches a terminal state (activity + SSE event)."""

    async def finalize(
        self,
        *,
        run: AdviceRun,
        state: str,
        activity_type: str,
        payload: dict[str, Any],
        system_context: str | None = None,
    ) -> None: ...


class AdviceWorker:
    """Claims queued runs, executes the trunk, and persists terminal state."""

    def __init__(
        self,
        *,
        repository: AdviceRunRepository,
        queue: AdviceQueue,
        incident_command: Any,
        sink: AdviceSink,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._command = incident_command
        self._sink = sink
        self._clock = clock or time.time

    async def enqueue(self, run: AdviceRun) -> None:
        await self._queue.enqueue(
            {
                "advice_run_id": run.run_id,
                "venue_id": run.venue_id,
                "incident_id": run.incident_id,
            }
        )

    async def run_run_id(
        self, *, venue_id: str, run_id: str
    ) -> AdviceFinalized | None:
        """Execute one durable run by id; used by the Hatchet workflow body."""

        run = await self._repository.get(venue_id=venue_id, run_id=run_id)
        if run is None or run.request is None:
            return None
        return await self._execute(run)

    async def run_once(self) -> AdviceFinalized | None:
        message = await self._queue.claim()
        if message is None:
            return None
        venue_id = str(message.get("venue_id") or "")
        run_id = str(message.get("advice_run_id") or "")
        run = await self._repository.get(venue_id=venue_id, run_id=run_id)
        if run is None or run.request is None:
            await self._queue.ack(message)
            return None
        return await self._execute(run)

    async def _execute(self, run: AdviceRun) -> AdviceFinalized:
        venue_id = run.venue_id
        run_id = run.run_id
        if run.state == "SUPERSEDED":
            # The human advanced first. Keep the model's late answer as read-only
            # evidence, but never publish a ready signal or let it reach dispatch.
            try:
                late = await self._command.execute(run.request)
            except Exception:
                late = None
            else:
                await self._repository.record_late_result(
                    venue_id=venue_id,
                    run_id=run_id,
                    response=late.model_dump(mode="json"),
                )
            current = await self._repository.get(venue_id=venue_id, run_id=run_id)
            return AdviceFinalized(run=current or run, state="SUPERSEDED")
        if run.state != "PENDING":
            return AdviceFinalized(run=run, state=run.state)

        if not await self._repository.transition(
            venue_id=venue_id,
            run_id=run_id,
            expected="PENDING",
            new_state="RUNNING",
            response={"advice_run_id": run_id, "incident_id": run.incident_id},
        ):
            current = await self._repository.get(venue_id=venue_id, run_id=run_id)
            return AdviceFinalized(
                run=current or run, state=(current.state if current else run.state)
            )

        try:
            result = await self._command.execute(run.request)
        except Exception as exc:  # provider/trunk failure
            transitioned = await self._repository.transition(
                venue_id=venue_id,
                run_id=run_id,
                expected="RUNNING",
                new_state="FAILED",
                error=exc,
            )
            final_run = await self._repository.get(venue_id=venue_id, run_id=run_id)
            if transitioned and final_run is not None:
                await self._sink.finalize(
                    run=final_run,
                    state="FAILED",
                    activity_type="ADVICE_FAILED",
                    payload={
                        "advice_run_id": run_id,
                        "state": "FAILED",
                        "error_type": type(exc).__name__,
                    },
                )
            return AdviceFinalized(run=final_run or run, state="FAILED")

        advice_state = "READY" if result.outcome in {"READY", "DEGRADED"} else "FAILED"
        response_body = result.model_dump(mode="json")
        transitioned = await self._repository.transition(
            venue_id=venue_id,
            run_id=run_id,
            expected="RUNNING",
            new_state=advice_state,
            response=response_body,
        )
        final_run = await self._repository.get(venue_id=venue_id, run_id=run_id)
        if final_run is None:
            return None

        if transitioned:
            await self._sink.finalize(
                run=final_run,
                state=advice_state,
                activity_type=(
                    "ADVICE_READY" if advice_state == "READY" else "ADVICE_FAILED"
                ),
                payload={
                    **response_body,
                    "advice_run_id": run_id,
                    "state": advice_state,
                },
            )
        elif final_run.state == "SUPERSEDED":
            # A human advanced first: the model result is kept as late evidence.
            await self._repository.record_late_result(
                venue_id=venue_id, run_id=run_id, response=response_body
            )
        return AdviceFinalized(run=final_run, state=final_run.state)


__all__ = [
    "ADVICE_COMMAND_TYPE",
    "AdviceFinalized",
    "AdviceQueue",
    "AdviceRun",
    "AdviceRunConflict",
    "AdviceRunRepository",
    "AdviceSink",
    "AdviceState",
    "AdviceWorker",
    "InMemoryAdviceQueue",
    "TERMINAL_STATES",
    "advice_idempotency_key",
    "advice_run_id",
]
