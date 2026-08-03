"""Persistent application-start recovery audit and safe diagnostics."""

from __future__ import annotations

import json
import os
import re
import socket
import time
import uuid
from typing import Any


GLOBAL_SCOPE = "GLOBAL"
GLOBAL_VENUE_ID = ""
_SAFE_LABEL = re.compile(r"[^A-Za-z0-9._:-]+")


def runtime_identity(
    *,
    instance_id: str | None = None,
    app_version: str | None = None,
) -> tuple[str, str]:
    """Return bounded, non-secret runtime labels for persisted diagnostics."""
    raw_instance = instance_id or os.environ.get("MEMORY_PALACE_INSTANCE_ID") or socket.gethostname()
    raw_version = app_version or os.environ.get("MEMORY_PALACE_VERSION") or "1.0.0"
    safe_instance = _SAFE_LABEL.sub("-", str(raw_instance)).strip("-")[:128] or "unknown-instance"
    safe_version = _SAFE_LABEL.sub("-", str(raw_version)).strip("-")[:64] or "unknown-version"
    return safe_instance, safe_version


def _count_value(row: dict[str, Any] | None, key: str) -> int:
    if not row:
        return 0
    return int(row.get(key) or 0)


class RuntimeRecoveryAudit:
    """One persisted global recovery run with append-only phase evidence."""

    def __init__(self, db: Any, *, run_id: str, trace_id: str):
        self._db = db
        self.id = run_id
        self.trace_id = trace_id
        self._trace: list[dict[str, Any]] = []

    @classmethod
    async def start(
        cls,
        db: Any,
        *,
        instance_id: str | None = None,
        app_version: str | None = None,
    ) -> "RuntimeRecoveryAudit":
        safe_instance, safe_version = runtime_identity(
            instance_id=instance_id,
            app_version=app_version,
        )
        run_id = uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        await db.execute(
            """
            INSERT INTO runtime_recovery_runs (
                id, scope_type, venue_id, instance_id, app_version, status,
                trace_id, trace_json, started_at
            ) VALUES (?, 'GLOBAL', '', ?, ?, 'RUNNING', ?, '[]', ?)
            """,
            (run_id, safe_instance, safe_version, trace_id, time.time()),
        )
        return cls(db, run_id=run_id, trace_id=trace_id)

    async def record_phase(
        self,
        phase: str,
        *,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        evidence = {"phase": phase, "status": status}
        evidence.update(details or {})
        self._trace.append(evidence)
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET trace_json = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (json.dumps(self._trace, ensure_ascii=False, sort_keys=True), self.id),
        )

    async def record_task_graph(self, *, recovered_count: int, reset_count: int) -> None:
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET task_graph_recovered_count = ?, task_graph_reset_count = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (recovered_count, reset_count, self.id),
        )
        await self.record_phase(
            "task_graph",
            status="SUCCEEDED",
            details={"recovered_count": recovered_count, "reset_count": reset_count},
        )

    async def record_approvals(self, *, interrupted_count: int, pending_loaded_count: int) -> None:
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET approval_interrupted_count = ?, approval_pending_loaded_count = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (interrupted_count, pending_loaded_count, self.id),
        )
        await self.record_phase(
            "approvals",
            status="SUCCEEDED",
            details={
                "interrupted_count": interrupted_count,
                "pending_loaded_count": pending_loaded_count,
            },
        )

    async def record_watcher(self, *, interrupted_count: int) -> None:
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET watcher_interrupted_count = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (interrupted_count, self.id),
        )
        await self.record_phase(
            "watcher",
            status="SUCCEEDED",
            details={"interrupted_count": interrupted_count},
        )

    async def record_redis(self, *, status: str, pending_count: int, claimed_count: int) -> None:
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET redis_status = ?, redis_pending_count = ?, redis_claimed_count = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (status, pending_count, claimed_count, self.id),
        )
        await self.record_phase(
            "redis",
            status=(
                "RUNNING"
                if status == "AVAILABLE" and pending_count > 0
                else "SUCCEEDED" if status == "AVAILABLE" else status
            ),
            details={
                "pending_count": pending_count,
                "claimed_count": claimed_count,
                "acked_count": 0,
            },
        )

    async def observe_redis_recovery(self, event: str, _message_id: str) -> None:
        if event == "claim":
            await self._db.execute(
                """
                UPDATE runtime_recovery_runs
                SET redis_claimed_count = redis_claimed_count + 1
                WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
                """,
                (self.id,),
            )
            return
        if event != "ack":
            return

        completed_at = time.time()
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET redis_acked_count = redis_acked_count + 1,
                status = CASE
                    WHEN redis_acked_count + 1 >= redis_claimed_count
                     AND redis_claimed_count > 0
                    THEN 'SUCCEEDED'
                    ELSE status
                END,
                completed_at = CASE
                    WHEN redis_acked_count + 1 >= redis_claimed_count
                     AND redis_claimed_count > 0
                    THEN ?
                    ELSE completed_at
                END
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
              AND redis_acked_count < redis_claimed_count
            """,
            (completed_at, self.id),
        )
        row = await self._db.fetch_one(
            """
            SELECT status, redis_pending_count, redis_claimed_count, redis_acked_count
            FROM runtime_recovery_runs
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (self.id,),
        )
        if not row or row.get("status") != "SUCCEEDED":
            return
        for phase in self._trace:
            if phase.get("phase") == "redis":
                phase.update(
                    {
                        "status": "SUCCEEDED",
                        "pending_count": int(row.get("redis_pending_count") or 0),
                        "claimed_count": int(row.get("redis_claimed_count") or 0),
                        "acked_count": int(row.get("redis_acked_count") or 0),
                    }
                )
                break
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET trace_json = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (json.dumps(self._trace, ensure_ascii=False, sort_keys=True), self.id),
        )

    async def complete(self) -> None:
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET status = 'SUCCEEDED', completed_at = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (time.time(), self.id),
        )

    async def fail(self, *, phase: str, error: BaseException) -> None:
        safe_summary = f"{phase} recovery failed ({type(error).__name__})"
        self._trace.append(
            {
                "phase": phase,
                "status": "FAILED",
                "error_type": type(error).__name__,
            }
        )
        redis_status = "UNAVAILABLE" if phase == "redis" else "NOT_CHECKED"
        await self._db.execute(
            """
            UPDATE runtime_recovery_runs
            SET status = 'FAILED', redis_status = CASE
                    WHEN ? = 'UNAVAILABLE' THEN 'UNAVAILABLE'
                    ELSE redis_status
                END,
                error_summary = ?, trace_json = ?, completed_at = ?
            WHERE id = ? AND scope_type = 'GLOBAL' AND venue_id = ''
            """,
            (
                redis_status,
                safe_summary,
                json.dumps(self._trace, ensure_ascii=False, sort_keys=True),
                time.time(),
                self.id,
            ),
        )


async def recover_application_runtime(
    db: Any,
    *,
    task_graph: Any,
    permission_engine: Any,
    runtime_queue: Any,
    instance_id: str | None = None,
    app_version: str | None = None,
) -> dict[str, str]:
    """Recover persisted runtime state and leave one durable global audit run."""
    audit = await RuntimeRecoveryAudit.start(
        db,
        instance_id=instance_id,
        app_version=app_version,
    )
    phase = "task_graph"
    try:
        task_counts = await db.fetch_one(
            """
            SELECT COUNT(*) AS recovered_count,
                   SUM(CASE WHEN status = 'RUNNING' THEN 1 ELSE 0 END) AS reset_count
            FROM tasks
            """
        )
        await task_graph.reload_from_db()
        await audit.record_task_graph(
            recovered_count=_count_value(task_counts, "recovered_count"),
            reset_count=_count_value(task_counts, "reset_count"),
        )

        phase = "approvals"
        approval_counts = await db.fetch_one(
            """
            SELECT SUM(CASE WHEN execution_status = 'EXECUTING' THEN 1 ELSE 0 END)
                       AS interrupted_count,
                   SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END)
                       AS pending_loaded_count
            FROM approval_requests
            """
        )
        await permission_engine.reload_from_db()
        await audit.record_approvals(
            interrupted_count=_count_value(approval_counts, "interrupted_count"),
            pending_loaded_count=_count_value(approval_counts, "pending_loaded_count"),
        )

        phase = "watcher"
        from .watcher_runtime import recover_interrupted_watcher_runs

        watcher_count = await recover_interrupted_watcher_runs(db)
        await audit.record_watcher(interrupted_count=int(watcher_count or 0))

        phase = "redis"
        await runtime_queue.connect()
        if hasattr(runtime_queue, "prepare_startup_recovery"):
            queue_recovery = await runtime_queue.prepare_startup_recovery()
        else:
            diagnostics = await runtime_queue.diagnostics()
            queue_recovery = {
                "status": "AVAILABLE" if diagnostics.get("connected") else "UNAVAILABLE",
                "pending": diagnostics.get("pending", 0),
                "claimed": 0,
            }
        queue_status = str(queue_recovery.get("status") or "AVAILABLE").upper()
        pending_count = int(queue_recovery.get("pending") or 0)
        claimed_count = int(queue_recovery.get("claimed") or 0)
        if queue_status != "AVAILABLE":
            await audit.record_redis(
                status=queue_status,
                pending_count=pending_count,
                claimed_count=claimed_count,
            )
            raise RuntimeError("Redis startup recovery is unavailable")
        if claimed_count != pending_count:
            await audit.record_redis(
                status="INCOMPLETE",
                pending_count=pending_count,
                claimed_count=claimed_count,
            )
            raise RuntimeError("Redis startup recovery has an incomplete pending claim")
        await audit.record_redis(
            status=queue_status,
            pending_count=pending_count,
            claimed_count=claimed_count,
        )
        runtime_queue.set_recovery_observer(audit.observe_redis_recovery)

        if pending_count == 0:
            await audit.complete()
            recovery_status = "SUCCEEDED"
        else:
            recovery_status = "RUNNING"
        return {"id": audit.id, "trace_id": audit.trace_id, "status": recovery_status}
    except BaseException as error:
        await audit.fail(phase=phase, error=error)
        raise


def public_recovery_run(row: dict[str, Any]) -> dict[str, Any]:
    """Map a global recovery record to its secret-free admin representation."""
    try:
        trace = json.loads(row.get("trace_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        trace = []
    return {
        "id": row["id"],
        "scope_type": row["scope_type"],
        "instance_id": row["instance_id"],
        "app_version": row["app_version"],
        "status": row["status"],
        "trace_id": row["trace_id"],
        "task_graph_recovered_count": int(row.get("task_graph_recovered_count") or 0),
        "task_graph_reset_count": int(row.get("task_graph_reset_count") or 0),
        "approval_interrupted_count": int(row.get("approval_interrupted_count") or 0),
        "approval_pending_loaded_count": int(row.get("approval_pending_loaded_count") or 0),
        "watcher_interrupted_count": int(row.get("watcher_interrupted_count") or 0),
        "redis_status": row.get("redis_status") or "NOT_CHECKED",
        "redis_pending_count": int(row.get("redis_pending_count") or 0),
        "redis_claimed_count": int(row.get("redis_claimed_count") or 0),
        "redis_acked_count": int(row.get("redis_acked_count") or 0),
        "error_summary": row.get("error_summary"),
        "trace": trace if isinstance(trace, list) else [],
        "started_at": row["started_at"],
        "completed_at": row.get("completed_at"),
    }


async def list_recent_global_recovery_runs(db: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Read only global recovery rows; tenant-scoped rows can never cross this boundary."""
    bounded_limit = max(1, min(int(limit), 100))
    rows = await db.fetch_all(
        """
        SELECT *
        FROM runtime_recovery_runs
        WHERE scope_type = 'GLOBAL' AND venue_id = ''
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (bounded_limit,),
    )
    return [public_recovery_run(row) for row in rows]
