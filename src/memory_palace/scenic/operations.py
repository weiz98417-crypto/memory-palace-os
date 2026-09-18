"""Deep module for scenic situation input and formal incident coordination."""

from __future__ import annotations

import hashlib
import asyncio
import json
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from ..core.business_ids import build_business_id
from ..core.event_activities import append_event_activity
from ..core.passwords import hash_password
from ..knowledge.reranking import rerank_candidates
from .advice_sink import DatabaseAdviceSink
from .adapters import MonitoringSignal, STORY
from .guidance import build_next_actions, project_advice


class ScenicCommandConflict(RuntimeError):
    pass


class ScenicPermissionDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class Actor:
    user_id: str
    username: str
    role: str
    venue_id: str


@dataclass(frozen=True)
class Command:
    kind: str
    payload: dict[str, Any]
    idempotency_key: str


Publisher = Callable[[dict[str, Any]], Awaitable[None]]


_ZONES = (
    {"id": "east-gate", "name": "东门集散区", "capacity": 1200, "x": 82, "y": 51},
    {"id": "vehicle-depot", "name": "观光车场站", "capacity": 180, "x": 55, "y": 76},
    {"id": "mountain-road", "name": "山地游线", "capacity": 650, "x": 37, "y": 36},
    {"id": "lake-zone", "name": "镜湖游览区", "capacity": 900, "x": 62, "y": 25},
)

_LIFECYCLE_ORDER = (
    "DETECTED",
    "TRIAGED",
    "DISPATCHED",
    "ACKNOWLEDGED",
    "MITIGATING",
    "RESOLVED",
    "CLOSED",
)



class ScenicAdviceSink:
    """Advice-run projection for the API process.

    Execution of the durable run happens in the Hatchet worker, which uses the same
    `DatabaseAdviceSink`; this wrapper only adds the in-process SSE publisher.
    """

    def __init__(self, operations: "ScenicAreaOperations") -> None:
        self._operations = operations
        database = getattr(operations, "database", None)
        if database is None:
            raise ValueError("advice sink requires an operations object with a database")
        self._sink = DatabaseAdviceSink(
            database, publisher=getattr(operations, "publisher", None)
        )

    async def finalize(
        self,
        *,
        run: Any,
        state: str,
        activity_type: str,
        payload: dict[str, Any],
        system_context: str | None = None,
    ) -> None:
        await self._sink.finalize(
            run=run,
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
        return await self._sink.project(
            venue_id=venue_id,
            incident_id=incident_id,
            run_id=run_id,
            state=state,
            activity_type=activity_type,
            payload=payload,
            system_context=system_context,
        )


class ScenicAreaOperations:
    """Execute commands and project the shared scenic-area business state."""

    def __init__(
        self,
        *,
        database,
        vector_store,
        task_graph,
        permission_engine,
        publisher: Optional[Publisher] = None,
        reranker: Any = None,
        advice_repository: Any = None,
        advice_decision_publisher: Any = None,
    ) -> None:
        self.database = database
        self.vector_store = vector_store
        self.task_graph = task_graph
        self.permission_engine = permission_engine
        self.publisher = publisher
        if reranker is None:
            from ..knowledge.reranking import build_reranker_backend

            reranker = build_reranker_backend()
        self.reranker = reranker
        self.advice_repository = advice_repository
        # Pushes the durable workflow's decision event; a no-op when the trunk runs
        # on the in-process dispatcher.
        self.advice_decision_publisher = advice_decision_publisher
        # Injected by main.py once the dispatcher exists; None keeps the auto-enqueue
        # disabled for the local stack and tests.
        self.advice_dispatcher = None
        self.advice_sink = ScenicAdviceSink(self)
        self._command_locks: dict[str, asyncio.Lock] = {}

    async def bootstrap(
        self,
        *,
        venue_id: str,
        venue_name: str,
        account_password: str,
    ) -> dict[str, str]:
        if len(account_password) < 12:
            raise ValueError("scenic account password must contain at least 12 characters")
        now = time.time()
        await self.database.execute(
            """
            INSERT INTO venues (id, name, status, created_at, updated_at)
            VALUES (?, ?, 'ACTIVE', ?, ?)
            ON CONFLICT(id) DO UPDATE SET name = excluded.name, status = 'ACTIVE', updated_at = excluded.updated_at
            """,
            (venue_id, venue_name, now, now),
        )
        accounts = (
            ("scenic-liming", "liming", "李明", "operator", "运营部", "现场运营员"),
            ("scenic-wangfang", "wangfang", "王芳", "manager", "指挥中心", "值班经理"),
            ("scenic-chenyu", "chenyu", "陈雨", "operator", "设备保障部", "设备检修员"),
            ("scenic-knowledge", "knowledge-owner", "赵敏", "manager", "运营标准部", "知识负责人"),
            ("scenic-simulation-ops", "simulation-ops", "运行准备员", "admin", "本地运维", "模拟环境运维"),
        )
        for user_id, username, display_name, role, department, job_title in accounts:
            existing = await self.database.fetch_one(
                "SELECT id FROM users WHERE username = ?", (username,)
            )
            password_hash = hash_password(account_password)
            if existing:
                await self.database.execute(
                    """
                    UPDATE users SET password_hash = ?, display_name = ?, role = ?, venue_id = ?,
                        status = 'ACTIVE', department = ?, job_title = ?, updated_at = ?
                    WHERE username = ?
                    """,
                    (
                        password_hash,
                        display_name,
                        role,
                        venue_id,
                        department,
                        job_title,
                        now,
                        username,
                    ),
                )
                user_id = str(existing["id"])
            else:
                await self.database.execute(
                    """
                    INSERT INTO users (
                        id, username, password_hash, display_name, role, venue_id,
                        status, department, job_title, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        password_hash,
                        display_name,
                        role,
                        venue_id,
                        department,
                        job_title,
                        now,
                        now,
                    ),
                )
            if username == "simulation-ops":
                continue
            identity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{venue_id}:wecom:{username}"))
            await self.database.execute(
                """
                INSERT INTO channel_identities (
                    id, venue_id, channel, external_tenant_id, external_user_id,
                    user_id, status, created_at, updated_at
                ) VALUES (?, ?, 'WECOM_SIMULATOR', ?, ?, ?, 'ACTIVE', ?, ?)
                ON CONFLICT(venue_id, channel, external_tenant_id, external_user_id)
                DO UPDATE SET user_id = excluded.user_id, status = 'ACTIVE', updated_at = excluded.updated_at
                """,
                (identity_id, venue_id, venue_id, username, user_id, now, now),
            )
            session_id = f"scenic-session-{username}"
            await self.database.execute(
                """
                INSERT INTO sessions (session_id, user_id, venue_id, stage, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET user_id = excluded.user_id,
                    venue_id = excluded.venue_id, stage = 'active', updated_at = excluded.updated_at
                """,
                (session_id, user_id, venue_id, now, now),
            )
            await self.database.execute(
                """
                INSERT INTO channel_conversations (
                    session_id, venue_id, channel, external_conversation_id,
                    user_id, status, created_at, updated_at
                ) VALUES (?, ?, 'WECOM_SIMULATOR', ?, ?, 'ACTIVE', ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET user_id = excluded.user_id,
                    status = 'ACTIVE', updated_at = excluded.updated_at
                """,
                (session_id, venue_id, f"scenic-{username}", user_id, now, now),
            )
        return {"venue_id": venue_id, "venue_name": venue_name}

    async def execute(self, actor: Actor, command: Command) -> dict[str, Any]:
        lock_key = f"{actor.venue_id}:{command.idempotency_key}"
        lock = self._command_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            return await self._execute_locked(actor, command)

    async def _execute_locked(self, actor: Actor, command: Command) -> dict[str, Any]:
        command_type = command.kind.strip().upper()
        if not command.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        request_hash = hashlib.sha256(
            json.dumps(
                {"type": command_type, "payload": command.payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        command_id = uuid.uuid4().hex
        now = time.time()
        await self.database.execute(
            """
            INSERT INTO scenic_commands (
                id, venue_id, command_type, idempotency_key, request_hash,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'PROCESSING', ?, ?)
            ON CONFLICT (venue_id, idempotency_key) DO NOTHING
            """,
            (
                command_id,
                actor.venue_id,
                command_type,
                command.idempotency_key,
                request_hash,
                now,
                now,
            ),
        )
        existing = await self.database.fetch_one(
            "SELECT * FROM scenic_commands WHERE venue_id = ? AND idempotency_key = ?",
            (actor.venue_id, command.idempotency_key),
        )
        if existing["request_hash"] != request_hash:
            raise ScenicCommandConflict("Idempotency-Key has already been used for another command")
        if existing["id"] != command_id:
            if existing["status"] == "SUCCEEDED":
                return _json_object(existing["response_json"])
            if existing["status"] == "PROCESSING":
                raise ScenicCommandConflict("command with this Idempotency-Key is already processing")
            claimed = await self.database.execute(
                """
                UPDATE scenic_commands SET id = ?, status = 'PROCESSING',
                    error_type = NULL, error_message = NULL, updated_at = ?
                WHERE id = ? AND status = 'FAILED' AND request_hash = ?
                """,
                (command_id, now, existing["id"], request_hash),
            )
            if claimed != 1:
                raise ScenicCommandConflict("command retry could not acquire its Idempotency-Key")
        try:
            handler = getattr(self, f"_command_{command_type.lower()}", None)
            if handler is None:
                raise ValueError(f"unsupported scenic command: {command_type}")
            result = await handler(actor, command.payload, command.idempotency_key)
        except Exception as exc:
            await self.database.execute(
                """
                UPDATE scenic_commands SET status = 'FAILED', error_type = ?,
                    error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    type(exc).__name__,
                    str(exc),
                    time.time(),
                    command_id,
                ),
            )
            raise
        await self.database.execute(
            """
            UPDATE scenic_commands SET status = 'SUCCEEDED', response_json = ?,
                error_type = NULL, error_message = NULL, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                time.time(),
                command_id,
            ),
        )
        return result

    async def snapshot(self, actor: Actor) -> dict[str, Any]:
        run = await self._current_run(actor.venue_id, required=False)
        if not run:
            return self._empty_snapshot(actor.venue_id)
        signals = await self.database.fetch_all(
            """
            SELECT * FROM scenic_monitoring_signals
            WHERE venue_id = ? AND run_id = ? ORDER BY simulated_at, source_sequence
            """,
            (actor.venue_id, run["id"]),
        )
        alerts = await self.database.fetch_all(
            """
            SELECT * FROM scenic_situation_alerts
            WHERE venue_id = ? AND run_id = ? ORDER BY created_at
            """,
            (actor.venue_id, run["id"]),
        )
        incidents = await self.database.fetch_all(
            """
            SELECT scenic.*, event.business_id, event.status AS event_status,
                   event.assigned_to, event.resolution
            FROM scenic_incidents scenic
            JOIN confirmed_events event ON event.event_id = scenic.event_id
            WHERE scenic.venue_id = ? AND scenic.run_id = ?
            ORDER BY scenic.created_at
            """,
            (actor.venue_id, run["id"]),
        )
        latest = await self.database.fetch_one(
            "SELECT MAX(sequence) AS sequence FROM scenic_situation_events WHERE venue_id = ?",
            (actor.venue_id,),
        )
        alert_views = [_alert_view(row) for row in alerts]
        incident_views = [await self._incident_view(row, alerts=alert_views) for row in incidents]
        primary_incident = incident_views[0] if incident_views else None
        primary_advice = primary_incident.get("advice") if primary_incident else None
        return {
            "venue_id": actor.venue_id,
            "run": _run_view(run),
            "signals": [_signal_view(row) for row in signals],
            "alerts": alert_views,
            "incidents": incident_views,
            "next_actions": build_next_actions(
                run=run,
                alerts=alert_views,
                incident=primary_incident,
                advice=primary_advice,
            ),
            "advice": primary_advice,
            "latest_sequence": int((latest or {}).get("sequence") or 0),
            "map": {
                "adapter": "OFFLINE_SVG",
                "coordinate_system": "LOCAL_SCENIC_GRID_V1",
                "zones": list(_ZONES),
                "routes": [
                    {"id": "route-east-loop", "from": "east-gate", "to": "vehicle-depot"},
                    {"id": "route-lake", "from": "east-gate", "to": "lake-zone"},
                ],
                "gis_connector": {
                    "status": "OPTIONAL_CONNECTION / NOT_CONFIGURED",
                    "interface": "ScenicMapAdapter/v1",
                    "coordinate_systems": ["WGS84", "GCJ02"],
                    "layers": ["zones", "routes", "equipment", "staff", "alerts"],
                },
            },
            "channel_connectors": {
                "internal": {"adapter": "WECOM_SIMULATOR_OUTBOX", "status": "READY"},
                "sms": {"adapter": "SMS", "status": "NOT_CONFIGURED"},
                "voice": {"adapter": "VOICE", "status": "NOT_CONFIGURED"},
            },
        }

    async def events_since(
        self, actor: Actor, *, after_sequence: int, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = await self.database.fetch_all(
            """
            SELECT * FROM scenic_situation_events
            WHERE venue_id = ? AND sequence > ?
            ORDER BY sequence ASC LIMIT ?
            """,
            (actor.venue_id, max(0, after_sequence), min(max(1, limit), 1000)),
        )
        return [_event_view(row) for row in rows]

    async def reconcile_incident(self, venue_id: str, incident_id: str) -> Optional[str]:
        incident = await self.database.fetch_one(
            "SELECT * FROM scenic_incidents WHERE venue_id = ? AND incident_id = ?",
            (venue_id, incident_id),
        )
        if not incident:
            return None
        lifecycle = incident["lifecycle"]
        tasks = await self.database.fetch_all(
            "SELECT * FROM tasks WHERE venue_id = ? AND event_id = ? ORDER BY created_at",
            (venue_id, incident["event_id"]),
        )
        for task in tasks:
            if task["status"] == "RUNNING":
                await self._sync_notification_receipt(incident, task, "ACKNOWLEDGED")
            elif task["status"] == "DONE":
                await self._sync_notification_receipt(incident, task, "RECEIPT_RECORDED")
        repair_task = next(
            (task for task in tasks if task["id"] == incident.get("repair_task_id")),
            None,
        )
        if lifecycle == "DISPATCHED" and repair_task and repair_task["status"] == "RUNNING":
            lifecycle = await self._transition(incident, "ACKNOWLEDGED", "任务已由陈雨接单", "system")
            incident["lifecycle"] = lifecycle
        if lifecycle == "ACKNOWLEDGED" and repair_task and repair_task["status"] == "DONE":
            lifecycle = await self._transition(incident, "MITIGATING", "现场检查结果已提交", "system")
        return lifecycle

    async def reconcile_event(self, venue_id: str, event_id: str) -> Optional[str]:
        incident = await self.database.fetch_one(
            "SELECT incident_id FROM scenic_incidents WHERE venue_id = ? AND event_id = ?",
            (venue_id, event_id),
        )
        if not incident:
            return None
        return await self.reconcile_incident(venue_id, incident["incident_id"])

    async def advance_playing_clocks(self) -> int:
        runs = await self.database.fetch_all(
            "SELECT * FROM scenic_simulation_runs WHERE status = 'PLAYING' ORDER BY created_at"
        )
        advanced = 0
        for run in runs:
            now = time.time()
            last_wall_tick = float(run.get("last_wall_tick") or now)
            elapsed_wall = max(0.0, min(now - last_wall_tick, 5.0))
            seconds = max(1, int(round(elapsed_wall * float(run["speed"]))))
            old_time = float(run["simulated_at"])
            new_time = old_time + seconds
            await self.database.execute(
                "UPDATE scenic_simulation_runs SET simulated_at = ?, last_wall_tick = ?, updated_at = ? WHERE id = ? AND status = 'PLAYING'",
                (new_time, now, now, run["id"]),
            )
            system_actor = Actor(
                user_id="scenic-simulation-runtime",
                username="simulation-runtime",
                role="admin",
                venue_id=run["venue_id"],
            )
            previous_elapsed = int(old_time - float(run["started_simulated_at"]))
            current_elapsed = int(new_time - float(run["started_simulated_at"]))
            for signal in STORY.due(previous_elapsed, current_elapsed):
                await self._ingest_signal(
                    system_actor,
                    run,
                    signal,
                    idempotency_key=f"{run['id']}:story:{signal.offset_seconds}:{signal.source_key}",
                )
            await self._record_event(
                run["venue_id"],
                run["id"],
                "CLOCK_UPDATED",
                "simulation_run",
                run["id"],
                {"status": "PLAYING", "speed": float(run["speed"]), "seconds": seconds},
                new_time,
            )
            advanced += 1
        return advanced

    async def _command_prepare_scenario(self, actor, payload, idempotency_key):
        self._require_operations(actor)
        if self.vector_store is None:
            raise ScenicCommandConflict("pgvector is unavailable; scenario preparation stopped")
        await self._ensure_story_sop(actor)
        now = time.time()
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{actor.venue_id}:{idempotency_key}"))
        await self.database.execute(
            "UPDATE scenic_simulation_runs SET status = 'PAUSED', updated_at = ? WHERE venue_id = ? AND status = 'PLAYING'",
            (now, actor.venue_id),
        )
        await self.database.execute(
            """
            INSERT INTO scenic_simulation_runs (
                id, venue_id, scenario_key, scenario_version, status, speed,
                simulated_at, started_simulated_at, prepared_by, preparation_key,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'PAUSED', 1.0, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                actor.venue_id,
                STORY.key,
                STORY.version,
                STORY.start_time,
                STORY.start_time,
                actor.user_id,
                idempotency_key,
                now,
                now,
            ),
        )
        await self._audit(actor, "SCENIC_SCENARIO_PREPARED", "simulation_run", run_id, idempotency_key)
        await self._record_event(
            actor.venue_id,
            run_id,
            "SCENARIO_PREPARED",
            "simulation_run",
            run_id,
            {"scenario_key": STORY.key, "scenario_version": STORY.version},
            STORY.start_time,
        )
        return {
            "run_id": run_id,
            "scenario_key": STORY.key,
            "scenario_version": STORY.version,
            "status": "PAUSED",
            "simulated_at": STORY.start_time,
        }

    async def _command_clock_step(self, actor, payload, idempotency_key):
        self._require_operations(actor)
        seconds = int(payload.get("seconds", 1))
        if seconds < 1 or seconds > 300:
            raise ValueError("clock step seconds must be between 1 and 300")
        run = await self._current_run(actor.venue_id)
        old_time = float(run["simulated_at"])
        new_time = old_time + seconds
        await self.database.execute(
            "UPDATE scenic_simulation_runs SET simulated_at = ?, status = 'PAUSED', updated_at = ? WHERE id = ?",
            (new_time, time.time(), run["id"]),
        )
        previous_elapsed = int(old_time - float(run["started_simulated_at"]))
        current_elapsed = int(new_time - float(run["started_simulated_at"]))
        generated = []
        for signal in STORY.due(previous_elapsed, current_elapsed):
            generated.append(
                await self._ingest_signal(
                    actor,
                    run,
                    signal,
                    idempotency_key=f"{run['id']}:story:{signal.offset_seconds}:{signal.source_key}",
                )
            )
        await self._audit(actor, "SCENIC_CLOCK_STEPPED", "simulation_run", run["id"], idempotency_key)
        await self._record_event(
            actor.venue_id,
            run["id"],
            "CLOCK_UPDATED",
            "simulation_run",
            run["id"],
            {"status": "PAUSED", "seconds": seconds, "generated_signal_count": len(generated)},
            new_time,
        )
        return {
            "run_id": run["id"],
            "status": "PAUSED",
            "simulated_at": new_time,
            "generated_signals": generated,
        }

    async def _command_clock_play(self, actor, payload, idempotency_key):
        self._require_operations(actor)
        speed = float(payload.get("speed", 1.0))
        if speed not in {0.5, 1.0, 2.0, 4.0, 8.0}:
            raise ValueError("speed must be one of 0.5, 1, 2, 4, 8")
        run = await self._current_run(actor.venue_id)
        now = time.time()
        await self.database.execute(
            "UPDATE scenic_simulation_runs SET status = 'PLAYING', speed = ?, last_wall_tick = ?, updated_at = ? WHERE id = ?",
            (speed, now, now, run["id"]),
        )
        await self._audit(actor, "SCENIC_CLOCK_PLAYED", "simulation_run", run["id"], idempotency_key)
        return {"run_id": run["id"], "status": "PLAYING", "speed": speed}

    async def _command_clock_pause(self, actor, payload, idempotency_key):
        self._require_operations(actor)
        run = await self._current_run(actor.venue_id)
        await self.database.execute(
            "UPDATE scenic_simulation_runs SET status = 'PAUSED', updated_at = ? WHERE id = ?",
            (time.time(), run["id"]),
        )
        await self._audit(actor, "SCENIC_CLOCK_PAUSED", "simulation_run", run["id"], idempotency_key)
        return {"run_id": run["id"], "status": "PAUSED"}

    async def _command_inject_signal(self, actor, payload, idempotency_key):
        self._require_operations(actor)
        run = await self._current_run(actor.venue_id)
        source_type = str(payload.get("source_type") or "").upper()
        if source_type not in {"WEATHER", "DEVICE", "CROWD", "LOCATION", "OBSERVATION"}:
            raise ValueError("unsupported source_type")
        zone_id = str(payload.get("zone_id") or "")
        if zone_id not in {zone["id"] for zone in _ZONES}:
            raise ValueError("unknown scenic zone")
        signal = MonitoringSignal(
            offset_seconds=int(float(run["simulated_at"]) - float(run["started_simulated_at"])),
            source_type=source_type,
            source_adapter="MANUAL_INJECTION",
            source_key=str(payload.get("source_key") or uuid.uuid4().hex),
            zone_id=zone_id,
            signal_type=str(payload.get("signal_type") or "MANUAL_OBSERVATION"),
            payload=_json_object(payload.get("data")),
        )
        result = await self._ingest_signal(actor, run, signal, idempotency_key=idempotency_key)
        await self._audit(actor, "SCENIC_SIGNAL_INJECTED", "monitoring_signal", result["id"], idempotency_key)
        return result

    async def _command_convert_alert(self, actor, payload, idempotency_key):
        self._require_roles(actor, "manager", "admin")
        alert_ids = [str(item) for item in payload.get("alert_ids") or []]
        if not alert_ids:
            raise ValueError("at least one alert_id is required")
        placeholders = ",".join("?" for _ in alert_ids)
        alerts = await self.database.fetch_all(
            f"SELECT * FROM scenic_situation_alerts WHERE venue_id = ? AND id IN ({placeholders})",
            (actor.venue_id, *alert_ids),
        )
        if len(alerts) != len(set(alert_ids)):
            raise ScenicCommandConflict("one or more alerts are unavailable")
        if any(alert["status"] != "ACTIVE" for alert in alerts):
            raise ScenicCommandConflict("only active alerts can be converted")
        if not any(alert["rule_code"] == "VEHICLE_12_RIGHT_REAR_WHEEL" for alert in alerts):
            raise ScenicCommandConflict("the first incident requires the vehicle fault alert")
        already = next((alert.get("incident_id") for alert in alerts if alert.get("incident_id")), None)
        if already:
            row = await self.database.fetch_one(
                "SELECT * FROM scenic_incidents WHERE incident_id = ?", (already,)
            )
            return {"incident_id": already, "event_id": row["event_id"], "lifecycle": row["lifecycle"]}
        run_id = alerts[0]["run_id"]
        now = time.time()
        incident_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{actor.venue_id}:{idempotency_key}:incident"))
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{incident_id}:event"))
        business_id = build_business_id("SJ", event_id, now)
        reason = str(payload.get("reason") or "雨后复检发现 12 号观光车右后轮异常，需要人工处置")
        await self.database.execute(
            """
            INSERT INTO confirmed_events (
                event_id, business_id, push_id, from_user, raw_text, event_type,
                severity, context_trigger_data, memory_content, created_at,
                confirmed_at, venue_id, source_type, status, assigned_to,
                trace_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, '设备安全', 'P1', ?, ?, ?, ?, ?,
                      'SCENIC_ALERT', 'OPEN', ?, ?, ?)
            """,
            (
                event_id,
                business_id,
                alerts[0]["latest_signal_id"],
                actor.user_id,
                "雨后观光车异常：12 号观光车右后轮异常",
                json.dumps({"alert_ids": alert_ids, "reason": reason}, ensure_ascii=False),
                reason,
                now,
                now,
                actor.venue_id,
                actor.user_id,
                idempotency_key,
                now,
            ),
        )
        await self.database.execute(
            """
            INSERT INTO scenic_incidents (
                incident_id, event_id, run_id, venue_id, lifecycle, priority,
                title, conversion_reason, converted_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'DETECTED', 'P1', ?, ?, ?, ?, ?)
            """,
            (incident_id, event_id, run_id, actor.venue_id, "雨后观光车异常", reason, actor.user_id, now, now),
        )
        await self.database.execute(
            f"UPDATE scenic_situation_alerts SET incident_id = ?, updated_at = ? WHERE venue_id = ? AND id IN ({placeholders})",
            (incident_id, now, actor.venue_id, *alert_ids),
        )
        await self._audit(actor, "SCENIC_ALERT_CONVERTED", "scenic_incident", incident_id, idempotency_key)
        await self._record_event(
            actor.venue_id,
            run_id,
            "INCIDENT_CREATED",
            "scenic_incident",
            incident_id,
            {"event_id": event_id, "business_id": business_id, "lifecycle": "DETECTED", "priority": "P1"},
            float(await self._simulation_time(actor.venue_id)),
        )
        return {
            "incident_id": incident_id,
            "event_id": event_id,
            "business_id": business_id,
            "lifecycle": "DETECTED",
        }

    async def _sync_notification_receipt(self, incident, task, target_status):
        receipt = await self.database.fetch_one(
            "SELECT * FROM scenic_notification_receipts WHERE venue_id = ? AND task_id = ?",
            (incident["venue_id"], task["id"]),
        )
        if not receipt or receipt["status"] == target_status:
            return
        now = time.time()
        result_json = task.get("result") if target_status == "RECEIPT_RECORDED" else None
        await self.database.execute(
            """
            UPDATE scenic_notification_receipts
            SET status = ?, acknowledged_at = COALESCE(acknowledged_at, ?),
                receipt_at = CASE WHEN ? = 'RECEIPT_RECORDED' THEN ? ELSE receipt_at END,
                result_json = CASE WHEN ? = 'RECEIPT_RECORDED' THEN ? ELSE result_json END,
                updated_at = ?
            WHERE venue_id = ? AND task_id = ?
            """,
            (
                target_status,
                now,
                target_status,
                now,
                target_status,
                result_json,
                now,
                incident["venue_id"],
                task["id"],
            ),
        )
        await self._record_event(
            incident["venue_id"],
            incident["run_id"],
            "INTERNAL_NOTIFICATION_ACKNOWLEDGED" if target_status == "ACKNOWLEDGED" else "FIELD_RECEIPT_RECORDED",
            "task",
            task["id"],
            {"task_id": task["id"], "status": target_status},
            float(await self._simulation_time(incident["venue_id"])),
        )
    async def _command_add_evidence(self, actor, payload, idempotency_key):
        self._require_roles(actor, "operator", "manager", "admin")
        incident = await self._incident(actor.venue_id, str(payload.get("incident_id") or ""))
        if incident["lifecycle"] not in {"DETECTED", "TRIAGED"}:
            raise ScenicCommandConflict("field evidence is only accepted during detection or triage")
        text_content = str(payload.get("text") or "").strip()
        attachment_id = str(payload.get("attachment_id") or "").strip() or None
        if not text_content:
            raise ValueError("field evidence text is required")
        if attachment_id:
            attachment = await self.database.fetch_one(
                """
                SELECT id, owner_user_id, scan_status FROM message_attachments
                WHERE venue_id = ? AND id = ?
                """,
                (actor.venue_id, attachment_id),
            )
            if not attachment or attachment["owner_user_id"] != actor.user_id:
                raise ScenicCommandConflict("attachment is unavailable to the current employee")
            if attachment["scan_status"] not in {"PASSED", "CLEAN"}:
                raise ScenicCommandConflict("attachment has not passed the safety scan")
        evidence_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{actor.venue_id}:{idempotency_key}:evidence"))
        simulated_at = float(await self._simulation_time(actor.venue_id))
        now = time.time()
        await self.database.execute(
            """
            INSERT INTO scenic_event_evidence (
                id, venue_id, incident_id, evidence_type, text_content,
                attachment_id, submitted_by, simulated_at, recorded_at,
                idempotency_key
            ) VALUES (?, ?, ?, 'FIELD_REPORT', ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                actor.venue_id,
                incident["incident_id"],
                text_content,
                attachment_id,
                actor.user_id,
                simulated_at,
                now,
                idempotency_key,
            ),
        )
        await self._record_event(
            actor.venue_id,
            incident["run_id"],
            "FIELD_EVIDENCE_ADDED",
            "scenic_incident",
            incident["incident_id"],
            {
                "evidence_id": evidence_id,
                "submitted_by": actor.user_id,
                "has_attachment": bool(attachment_id),
                "summary": text_content,
            },
            simulated_at,
        )
        await self._audit(actor, "SCENIC_FIELD_EVIDENCE_ADDED", "scenic_incident", incident["incident_id"], idempotency_key)
        lifecycle = await self._maybe_triage(incident)
        return {
            "evidence_id": evidence_id,
            "incident_id": incident["incident_id"],
            "attachment_id": attachment_id,
            "lifecycle": lifecycle,
        }


    async def _auto_enqueue_advice(self, *, venue_id: str, incident_id: str) -> None:
        """Enqueue grounded advice right after retrieval, without a human click.

        A failure here must not fail the retrieval: the operator can still trigger advice
        explicitly, and the incident keeps moving on the manual path.
        """

        dispatcher = getattr(self, "advice_dispatcher", None)
        repository = self.advice_repository
        if dispatcher is None or repository is None:
            return
        try:
            from .advice_request import build_advice_request

            request, step = await build_advice_request(
                database=self.database, venue_id=venue_id, incident_id=incident_id
            )
            run, created = await repository.create_or_get(
                venue_id=venue_id,
                incident_id=incident_id,
                step=step,
                attempt=1,
                request=request,
            )
            if created:
                await dispatcher.dispatch(run)
                await self.advice_sink.project(
                    venue_id=run.venue_id,
                    incident_id=run.incident_id,
                    run_id=run.run_id,
                    state=run.state,
                    activity_type="ADVICE_PENDING",
                    payload={
                        "advice_run_id": run.run_id,
                        "state": run.state,
                        "trace_id": request.trace_id,
                        "step": step,
                        "attempt": 1,
                    },
                )
        except Exception as exc:
            logger.warning(
                "automatic advice enqueue failed for {}: {}", incident_id, type(exc).__name__
            )

    async def _command_retrieve_sop(self, actor, payload, idempotency_key):
        self._require_roles(actor, "manager", "admin")
        incident = await self._incident(actor.venue_id, str(payload.get("incident_id") or ""))
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("knowledge query is required")
        if self.vector_store is None:
            raise ScenicCommandConflict("pgvector is unavailable")
        hits = self.vector_store.query_experience(
            query,
            top_k=8,
            threshold=0.55,
            venue_id=actor.venue_id,
            source_types=["SOP"],
            strict=True,
        )
        rerank_input = [
            {
                "index": index,
                "id": hit.get("id"),
                "text": str(hit.get("text") or hit.get("content") or ""),
                "score": hit.get("score"),
                "metadata": hit.get("metadata"),
            }
            for index, hit in enumerate(hits)
        ]
        reranked, rerank_meta = rerank_candidates(
            self.reranker,
            query,
            rerank_input,
            top_n=5,
        )
        by_index = {int(item["index"]): item for item in reranked}
        ordered_hits = [
            (int(item["index"]), hits[int(item["index"])])
            for item in reranked
            if item.get("index") is not None and 0 <= int(item["index"]) < len(hits)
        ]
        if not ordered_hits:
            ordered_hits = list(enumerate(hits))
        verified = []
        now = time.time()
        for index, hit in ordered_hits:
            rerank_score = (by_index.get(index) or {}).get("rerank_score")
            metadata = _json_object(hit.get("metadata"))
            if str(metadata.get("source_type") or "").upper() != "SOP":
                continue
            source_id = str(metadata.get("source_id") or metadata.get("sop_id") or "")
            sop = await self.database.fetch_one(
                """
                SELECT id, version, title FROM sop_documents
                WHERE venue_id = ? AND CAST(id AS TEXT) = ? AND status = 'PUBLISHED'
                """,
                (actor.venue_id, source_id),
            )
            if not sop or str(sop["version"]) != str(metadata.get("version") or ""):
                continue
            hit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{actor.venue_id}:{idempotency_key}:{index}"))
            await self.database.execute(
                """
                INSERT INTO scenic_knowledge_hits (
                    id, venue_id, incident_id, query_text, vector_doc_id,
                    source_type, source_id, source_version, score, backend,
                    model_name, dimension, recorded_at, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, 'SOP', ?, ?, ?, ?, ?, 1024, ?, ?)
                """,
                (
                    hit_id,
                    actor.venue_id,
                    incident["incident_id"],
                    query,
                    str(hit["id"]),
                    source_id,
                    str(sop["version"]),
                    float(hit.get("score") or 0.0),
                    str(getattr(self.vector_store, "backend_mode", "postgresql_pgvector")),
                    str(getattr(self.vector_store, "model_name", "BAAI/bge-m3")),
                    now,
                    f"{idempotency_key}:{index}",
                ),
            )
            verified.append(
                {
                    "vector_doc_id": str(hit["id"]),
                    "source_type": "SOP",
                    "source_id": source_id,
                    "source_version": str(sop["version"]),
                    "title": sop["title"],
                    "score": float(hit.get("score") or 0.0),
                    "vector_score": float(hit.get("score") or 0.0),
                    "rerank_score": rerank_score,
                    "rerank_status": rerank_meta.get("rerank_status"),
                    "rerank_model": rerank_meta.get("rerank_model"),
                }
            )
        if not verified:
            raise ScenicCommandConflict("pgvector returned no verified published SOP")
        await self._record_event(
            actor.venue_id,
            incident["run_id"],
            "SOP_RETRIEVED",
            "scenic_incident",
            incident["incident_id"],
            {
                "query": query,
                "hits": verified,
                "backend": getattr(self.vector_store, "backend_mode", "postgresql_pgvector"),
                "rerank_status": rerank_meta.get("rerank_status"),
                "rerank_model": rerank_meta.get("rerank_model"),
            },
            float(await self._simulation_time(actor.venue_id)),
        )
        await self._audit(actor, "SCENIC_SOP_RETRIEVED", "scenic_incident", incident["incident_id"], idempotency_key)
        await self._auto_enqueue_advice(
            venue_id=actor.venue_id, incident_id=incident["incident_id"]
        )
        lifecycle = await self._maybe_triage(incident)
        return {
            "incident_id": incident["incident_id"],
            "backend": str(getattr(self.vector_store, "backend_mode", "postgresql_pgvector")),
            "model_name": str(getattr(self.vector_store, "model_name", "BAAI/bge-m3")),
            "dimension": 1024,
            "hits": verified,
            "lifecycle": lifecycle,
        }

    async def _command_decide_advice(self, actor, payload, idempotency_key):
        self._require_roles(actor, "manager", "admin")
        incident_id = str(payload.get("incident_id") or "")
        incident = await self._incident(actor.venue_id, incident_id)
        activities = await self.database.fetch_all(
            """
            SELECT * FROM event_activities
            WHERE venue_id = ? AND event_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (actor.venue_id, incident["event_id"]),
        )
        advice = project_advice(activities)
        if not advice:
            raise ScenicCommandConflict("no advice run is available for decision")

        advice_run_id = str(payload.get("advice_run_id") or "")
        if not advice_run_id or advice_run_id != str(advice.get("run_id")):
            raise ScenicCommandConflict("advice decision must reference the current advice run")
        decision = str(payload.get("decision") or "").strip().upper()
        if decision not in advice.get("allowed_actions", []):
            raise ScenicCommandConflict("advice decision is not allowed for the current advice state")
        expected_state = str(payload.get("expected_state") or "").strip().upper()
        if expected_state and expected_state != str(advice.get("status")):
            raise ScenicCommandConflict("advice state changed before the decision was recorded")

        reason_code = str(payload.get("reason_code") or "").strip().upper() or None
        reason_text = str(payload.get("reason_text") or "").strip() or None
        if decision in {"IGNORE", "PROCEED_WITHOUT_WAITING"}:
            if reason_code not in {"NO_BASIS", "NOT_APPLICABLE", "EVIDENCE_CONFLICT", "HUMAN_JUDGMENT", "OTHER"}:
                raise ValueError("reason_code is required for ignore or proceed decisions")
            if reason_code == "OTHER" and not reason_text:
                raise ValueError("reason_text is required when reason_code is OTHER")

        decided_at = time.time()
        supersedes_pending = decision == "PROCEED_WITHOUT_WAITING" and advice["status"] in {
            "PENDING",
            "RUNNING",
        }
        durable_run = None
        if self.advice_repository is not None:
            durable_run = await self.advice_repository.get(
                venue_id=actor.venue_id, run_id=advice_run_id
            )
            if durable_run is not None:
                if durable_run.state == "SUPERSEDED":
                    raise ScenicCommandConflict(
                        "a superseded advice cannot be decided again"
                    )
                if str(advice["status"]) != durable_run.state:
                    raise ScenicCommandConflict(
                        "advice state changed before the decision was recorded"
                    )
                if supersedes_pending:
                    superseded = await self.advice_repository.transition(
                        venue_id=actor.venue_id,
                        run_id=advice_run_id,
                        expected=("PENDING", "RUNNING"),
                        new_state="SUPERSEDED",
                        response={
                            "advice_run_id": advice_run_id,
                            "incident_id": incident_id,
                            "superseded_by": actor.user_id,
                            "reason_code": reason_code,
                            "reason_text": reason_text,
                        },
                        system_context="PROCEED_WITHOUT_WAITING",
                    )
                    if not superseded:
                        raise ScenicCommandConflict(
                            "advice run changed before it could be superseded"
                        )
        activity_type = "ADVICE_SUPERSEDED" if supersedes_pending else "ADVICE_DECIDED"
        activity_payload = {
            "decision": decision,
            "incident_id": incident_id,
            "advice_run_id": advice_run_id,
            "expected_advice_state": advice["status"],
            "reason_code": reason_code,
            "reason_text": reason_text,
            "system_context": "EVENT_CLOSED" if activity_type == "ADVICE_SUPERSEDED" and payload.get("system_context") == "EVENT_CLOSED" else None,
            "decided_by": actor.user_id,
            "decided_at": decided_at,
            "superseded_by": actor.user_id if supersedes_pending else None,
        }
        await append_event_activity(
            self.database,
            venue_id=actor.venue_id,
            event_id=incident["event_id"],
            activity_type=activity_type,
            created_by=actor.user_id,
            trace_id=advice.get("trace_id"),
            payload=activity_payload,
            idempotency_key=f"advice-decision:{advice_run_id}:{decision}:{idempotency_key}",
            created_at=decided_at,
        )
        await self._record_event(
            actor.venue_id,
            incident["run_id"],
            "ADVICE_READY" if activity_type == "ADVICE_SUPERSEDED" else activity_type,
            "scenic_advice",
            advice_run_id,
            {
                "state": "SUPERSEDED" if supersedes_pending else "DECIDED",
                "decision": decision,
                "advice_run_id": advice_run_id,
                "reason_code": reason_code,
                "reason_text": reason_text,
                "superseded_by": activity_payload["superseded_by"],
            },
            float(await self._simulation_time(actor.venue_id)),
        )
        await self._audit(actor, f"SCENIC_{activity_type}", "scenic_advice", advice_run_id, idempotency_key)
        if self.advice_decision_publisher is not None:
            try:
                await self.advice_decision_publisher(
                    incident_id=incident_id,
                    advice_run_id=advice_run_id,
                    decision=decision,
                    decided_by=actor.user_id,
                    reason_code=reason_code,
                    reason_text=reason_text,
                )
            except Exception as exc:  # a resume failure must not lose the decision
                logger.warning(
                    "could not resume the durable advice workflow: {}", type(exc).__name__
                )
        return {
            "incident_id": incident_id,
            "advice_run_id": advice_run_id,
            "decision": decision,
            "activity_type": activity_type,
            "superseded": supersedes_pending,
            "advice_state": "SUPERSEDED" if supersedes_pending else advice["status"],
        }
    async def _command_create_repair_task(self, actor, payload, idempotency_key):
        self._require_roles(actor, "manager", "admin")
        incident = await self._incident(actor.venue_id, str(payload.get("incident_id") or ""))
        if incident["lifecycle"] != "TRIAGED":
            raise ScenicCommandConflict("repair task requires a TRIAGED incident")
        remaining = self.permission_engine.cooldown_remaining(
            "record_manager_decision", actor.venue_id
        )
        if remaining > 0:
            raise ScenicCommandConflict(
                "high-risk vehicle decision did not enter approval; "
                f"retry after {math.ceil(remaining)}s"
            )
        technician = await self._user(actor.venue_id, "chenyu")
        session_id = "scenic-session-chenyu"
        task = await self.task_graph.create_task(
            session_id=session_id,
            description="检查 12 号观光车右后轮并核验 7 号备用车辆",
            assigned_agent="field-technician",
            assigned_user_id=technician["id"],
            venue_id=actor.venue_id,
            event_id=incident["event_id"],
            due_at=float(await self._simulation_time(actor.venue_id)) + 20 * 60,
            result_schema_json={
                "type": "object",
                "required": ["vehicle_12", "backup_vehicle_7", "inspection_items"],
                "properties": {
                    "vehicle_12": {"type": "string"},
                    "backup_vehicle_7": {"type": "string"},
                    "inspection_items": {"type": "array", "items": {"type": "string"}},
                },
            },
        )
        approval_result = await self.permission_engine.check_and_execute(
            "record_manager_decision",
            {
                "decision": "CONTINUE_SUSPENSION_AND_ACTIVATE_BACKUP",
                "message": "继续停运 12 号载客观光车并启用 7 号备用车辆",
            },
            {
                "session_id": session_id,
                "user_id": actor.user_id,
                "agent_name": "ScenicAreaOperations",
                "venue_id": actor.venue_id,
                "event_id": incident["event_id"],
                "task_id": task.id,
                "idempotency_key": f"{idempotency_key}:vehicle-decision",
                "trace_id": idempotency_key,
                "evidence_snapshot": {
                    "event_business_id": (
                        await self.database.fetch_one(
                            "SELECT business_id FROM confirmed_events WHERE event_id = ?",
                            (incident["event_id"],),
                        )
                    )["business_id"],
                    "task": task.to_dict(),
                    "decision_codes": [
                        "SUSPEND_PASSENGER_VEHICLE",
                        "ACTIVATE_BACKUP_VEHICLE",
                    ],
                },
            },
        )
        if approval_result.get("status") != "pending_approval":
            await self.task_graph.delete_tasks([task.id], venue_id=actor.venue_id)
            raise ScenicCommandConflict(
                "high-risk vehicle decision did not enter approval; the dispatch was rolled back"
            )
        await self.database.execute(
            """
            UPDATE scenic_incidents SET repair_task_id = ?, decision_approval_id = ?, updated_at = ?
            WHERE incident_id = ?
            """,
            (task.id, approval_result["approval_id"], time.time(), incident["incident_id"]),
        )
        await self._notify_assignee(
            actor,
            incident,
            task.to_dict(),
            session_id=session_id,
            message="雨后复检任务：检查 12 号观光车右后轮，审批通过后执行停运与备用车方案。",
            idempotency_key=f"{idempotency_key}:notify-chenyu",
        )
        lifecycle = await self._transition(incident, "DISPATCHED", "检修任务与高风险审批已生成", actor.user_id)
        await self._audit(actor, "SCENIC_REPAIR_TASK_CREATED", "task", task.id, idempotency_key)
        return {
            "incident_id": incident["incident_id"],
            "lifecycle": lifecycle,
            "task": task.to_dict(),
            "approval_id": approval_result["approval_id"],
            "approval_business_id": approval_result["business_id"],
        }

    async def _command_create_diversion_task(self, actor, payload, idempotency_key):
        self._require_roles(actor, "manager", "admin")
        incident = await self._incident(actor.venue_id, str(payload.get("incident_id") or ""))
        if incident["lifecycle"] != "MITIGATING":
            raise ScenicCommandConflict("diversion task requires an incident under mitigation")
        alert = await self.database.fetch_one(
            """
            SELECT * FROM scenic_situation_alerts
            WHERE venue_id = ? AND run_id = ? AND rule_code = 'EAST_GATE_CAPACITY'
              AND status = 'ACTIVE'
            """,
            (actor.venue_id, incident["run_id"]),
        )
        if not alert:
            raise ScenicCommandConflict("east gate crowd alert is not active")
        operator = await self._user(actor.venue_id, "liming")
        session_id = "scenic-session-liming"
        task = await self.task_graph.create_task(
            session_id=session_id,
            description="执行东门客流单向分流并回报恢复情况",
            dependencies=[incident["repair_task_id"]],
            assigned_agent="field-operator",
            assigned_user_id=operator["id"],
            venue_id=actor.venue_id,
            event_id=incident["event_id"],
            due_at=float(await self._simulation_time(actor.venue_id)) + 10 * 60,
            result_schema_json={
                "type": "object",
                "required": ["diversion_action", "risk_status"],
                "properties": {
                    "diversion_action": {"type": "string"},
                    "risk_status": {"type": "string"},
                },
            },
        )
        await self.database.execute(
            "UPDATE scenic_incidents SET diversion_task_id = ?, updated_at = ? WHERE incident_id = ?",
            (task.id, time.time(), incident["incident_id"]),
        )
        await self.database.execute(
            "UPDATE scenic_situation_alerts SET incident_id = ?, updated_at = ? WHERE id = ?",
            (incident["incident_id"], time.time(), alert["id"]),
        )
        await self._notify_assignee(
            actor,
            incident,
            task.to_dict(),
            session_id=session_id,
            message="东门客流超过容量阈值，请执行单向分流并提交现场结果。",
            idempotency_key=f"{idempotency_key}:notify-liming",
        )
        await self._record_event(
            actor.venue_id,
            incident["run_id"],
            "DIVERSION_TASK_CREATED",
            "task",
            task.id,
            {"task": task.to_dict(), "alert_id": alert["id"]},
            float(await self._simulation_time(actor.venue_id)),
        )
        await self._audit(actor, "SCENIC_DIVERSION_TASK_CREATED", "task", task.id, idempotency_key)
        return {"incident_id": incident["incident_id"], "lifecycle": incident["lifecycle"], "task": task.to_dict()}

    async def _command_resolve_incident(self, actor, payload, idempotency_key):
        self._require_roles(actor, "manager", "admin")
        incident = await self._incident(actor.venue_id, str(payload.get("incident_id") or ""))
        if incident["lifecycle"] != "MITIGATING":
            raise ScenicCommandConflict("incident must be MITIGATING before resolution")
        tasks = await self.database.fetch_all(
            "SELECT id, status FROM tasks WHERE venue_id = ? AND event_id = ?",
            (actor.venue_id, incident["event_id"]),
        )
        if len(tasks) < 2 or any(task["status"] != "DONE" for task in tasks):
            raise ScenicCommandConflict("all repair and diversion tasks must be completed")
        approval = await self.database.fetch_one(
            "SELECT status, execution_status FROM approval_requests WHERE venue_id = ? AND approval_id = ?",
            (actor.venue_id, incident["decision_approval_id"]),
        )
        if not approval or approval["status"] != "APPROVED" or approval["execution_status"] != "SUCCEEDED":
            raise ScenicCommandConflict("vehicle decision approval must succeed")
        evidence = await self.database.fetch_one(
            "SELECT id FROM scenic_event_evidence WHERE venue_id = ? AND incident_id = ? AND attachment_id IS NOT NULL",
            (actor.venue_id, incident["incident_id"]),
        )
        knowledge = await self.database.fetch_one(
            "SELECT id FROM scenic_knowledge_hits WHERE venue_id = ? AND incident_id = ? AND source_type = 'SOP'",
            (actor.venue_id, incident["incident_id"]),
        )
        active_alert = await self.database.fetch_one(
            "SELECT id FROM scenic_situation_alerts WHERE venue_id = ? AND incident_id = ? AND status = 'ACTIVE'",
            (actor.venue_id, incident["incident_id"]),
        )
        if not evidence or not knowledge:
            raise ScenicCommandConflict("field image evidence and a verified SOP hit are required")
        if active_alert:
            raise ScenicCommandConflict("linked situation alerts must recover before resolution")
        lifecycle = await self._transition(incident, "RESOLVED", "任务、审批、证据齐全且告警已恢复", actor.user_id)
        await self._audit(actor, "SCENIC_INCIDENT_RESOLVED", "scenic_incident", incident["incident_id"], idempotency_key)
        return {"incident_id": incident["incident_id"], "lifecycle": lifecycle}

    async def _command_close_incident(self, actor, payload, idempotency_key):
        self._require_roles(actor, "manager", "admin")
        incident = await self._incident(actor.venue_id, str(payload.get("incident_id") or ""))
        if incident["lifecycle"] not in {"RESOLVED", "CLOSED"}:
            raise ScenicCommandConflict("incident must be RESOLVED before it can be CLOSED")
        vector_doc_id = f"evt_{incident['event_id']}"
        self.vector_store.upsert_experience(
            "雨后 12 号观光车右后轮异常处置：继续停运故障车辆，启用备用车辆，东门客流上升后完成分流。",
            {
                "venue_id": actor.venue_id,
                "source_type": "CASE",
                "source_id": incident["event_id"],
                "event_id": incident["event_id"],
                "version": "1",
                "status": "CLOSED",
                "title": "雨后观光车异常与东门分流闭环",
            },
            vector_doc_id,
            strict=True,
        )
        if incident["lifecycle"] == "RESOLVED":
            await self._transition(incident, "CLOSED", "授权负责人确认事件关闭", actor.user_id)
        now = time.time()
        await self.database.execute(
            """
            UPDATE confirmed_events SET status = 'CLOSED', resolution = ?, closed_at = ?, updated_at = ?
            WHERE venue_id = ? AND event_id = ?
            """,
            ("12 号车保持停运并启用备用车辆；东门完成分流，风险解除。", now, now, actor.venue_id, incident["event_id"]),
        )
        await self.database.execute(
            "UPDATE confirmed_events SET vector_doc_id = ? WHERE venue_id = ? AND event_id = ?",
            (vector_doc_id, actor.venue_id, incident["event_id"]),
        )
        await self._audit(actor, "SCENIC_INCIDENT_CLOSED", "scenic_incident", incident["incident_id"], idempotency_key)
        return {"incident_id": incident["incident_id"], "lifecycle": "CLOSED", "dossier_ready": True}

    async def _maybe_triage(self, incident):
        if incident["lifecycle"] != "DETECTED":
            return incident["lifecycle"]
        evidence = await self.database.fetch_one(
            "SELECT id FROM scenic_event_evidence WHERE venue_id = ? AND incident_id = ?",
            (incident["venue_id"], incident["incident_id"]),
        )
        knowledge = await self.database.fetch_one(
            "SELECT id FROM scenic_knowledge_hits WHERE venue_id = ? AND incident_id = ?",
            (incident["venue_id"], incident["incident_id"]),
        )
        if not evidence or not knowledge:
            return "DETECTED"
        return await self._transition(incident, "TRIAGED", "现场证据与雨后复运 SOP 已核验", "system")

    async def _notify_assignee(
        self,
        actor,
        incident,
        task,
        *,
        session_id,
        message,
        idempotency_key,
    ):
        push_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{actor.venue_id}:{idempotency_key}:push"))
        await self.database.execute(
            """
            INSERT INTO push_logs (
                push_id, venue_id, msg_id, from_user, raw_text, event_type,
                severity, stage1_triggered, hit_keywords, pushed_at,
                adoption_status, trace_id, channel, recipient,
                delivery_status, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, '景区运营通知', 'P1', ?, '[]', ?,
                      'pending', ?, 'WECOM_SIMULATOR_OUTBOX', ?, 'DELIVERED', ?)
            ON CONFLICT(venue_id, channel, idempotency_key) DO NOTHING
            """,
            (
                push_id,
                actor.venue_id,
                incident["event_id"],
                actor.user_id,
                message,
                False,
                time.time(),
                idempotency_key,
                f"session:{session_id}",
                idempotency_key,
            ),
        )
        delivered_at = time.time()
        await self.database.execute(
            """
            INSERT INTO scenic_notification_receipts (
                id, venue_id, incident_id, task_id, push_id, session_id,
                status, delivered_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'DELIVERED', ?, ?)
            ON CONFLICT(venue_id, task_id) DO NOTHING
            """,
            (
                str(uuid.uuid5(uuid.NAMESPACE_URL, f"{actor.venue_id}:{task['id']}:notification")),
                actor.venue_id,
                incident["incident_id"],
                task["id"],
                push_id,
                session_id,
                delivered_at,
                delivered_at,
            ),
        )
        await self._record_event(
            actor.venue_id,
            incident["run_id"],
            "INTERNAL_NOTIFICATION_DELIVERED",
            "push_log",
            push_id,
            {
                "channel": "WECOM_SIMULATOR_OUTBOX",
                "delivery_status": "DELIVERED",
                "recipient": f"session:{session_id}",
                "task_id": task["id"],
            },
            float(await self._simulation_time(actor.venue_id)),
        )

    async def _user(self, venue_id, username):
        row = await self.database.fetch_one(
            "SELECT * FROM users WHERE venue_id = ? AND username = ? AND status = 'ACTIVE'",
            (venue_id, username),
        )
        if not row:
            raise ScenicCommandConflict(f"required seeded account is unavailable: {username}")
        return row

    async def _ensure_story_sop(self, actor: Actor) -> dict[str, Any]:
        title = "雨后观光车复运与分流 SOP"
        sop = await self.database.fetch_one(
            "SELECT * FROM sop_documents WHERE venue_id = ? AND title = ?",
            (actor.venue_id, title),
        )
        now = time.time()
        content = (
            "连续降雨结束后，载客观光车必须完成轮胎、制动和底盘复检。发现轮组异常时继续停运故障车辆，"
            "由值班经理审批启用备用车辆；客流超过区域阈值时追加东门分流任务。检修回执、现场图片、"
            "审批结果和客流恢复证据齐全后，方可解除风险并关闭事件。"
        )
        if not sop:
            await self.database.execute(
                """
                INSERT INTO sop_documents (
                    venue_id, category, title, content, priority, version, status,
                    created_by, reviewed_by, published_at, created_at, updated_at
                    ) VALUES (?, '设备与客流联动', ?, ?, 1, '1.0', 'DRAFT', ?, ?, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (actor.venue_id, title, content, actor.user_id, actor.user_id),
            )
            sop = await self.database.fetch_one(
                "SELECT * FROM sop_documents WHERE venue_id = ? AND title = ?",
                (actor.venue_id, title),
            )
            await self.database.execute(
                """
                INSERT INTO sop_versions (
                    id, sop_id, venue_id, version, title, content, status,
                    changed_by, change_note, created_at
                ) VALUES (?, ?, ?, '1.0', ?, ?, 'DRAFT', ?, '景区垂直切片预置版本', ?)
                """,
                (f"scenic-sop-{sop['id']}-v1", sop["id"], actor.venue_id, title, content, actor.user_id, now),
            )
        vector_doc_id = f"sop:{actor.venue_id}:{sop['id']}"
        self.vector_store.upsert_experience(
            content,
            {
                "venue_id": actor.venue_id,
                "source_type": "SOP",
                "source_id": str(sop["id"]),
                "sop_id": str(sop["id"]),
                "title": title,
                "version": "1.0",
                "status": "PUBLISHED",
            },
            vector_doc_id,
            strict=True,
        )
        await self.database.execute(
            "UPDATE sop_documents SET status = 'PUBLISHED', published_at = ?, reviewed_by = ?, updated_at = CURRENT_TIMESTAMP WHERE venue_id = ? AND id = ?",
            (now, actor.user_id, actor.venue_id, sop["id"]),
        )
        await self.database.execute(
            "UPDATE sop_versions SET status = 'PUBLISHED' WHERE venue_id = ? AND sop_id = ? AND version = '1.0'",
            (actor.venue_id, sop["id"]),
        )
        return {"sop_id": str(sop["id"]), "vector_doc_id": vector_doc_id}

    async def _ingest_signal(self, actor, run, signal: MonitoringSignal, *, idempotency_key):
        existing = await self.database.fetch_one(
            "SELECT * FROM scenic_monitoring_signals WHERE venue_id = ? AND idempotency_key = ?",
            (actor.venue_id, idempotency_key),
        )
        if existing:
            return _signal_view(existing)
        sequence = await self.database.fetch_one(
            "SELECT COALESCE(MAX(source_sequence), 0) + 1 AS next_sequence FROM scenic_monitoring_signals WHERE run_id = ?",
            (run["id"],),
        )
        signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{actor.venue_id}:{idempotency_key}:signal"))
        simulated_at = float(run["started_simulated_at"]) + signal.offset_seconds
        recorded_at = time.time()
        await self.database.execute(
            """
            INSERT INTO scenic_monitoring_signals (
                id, run_id, venue_id, source_type, source_adapter, source_key,
                zone_id, signal_type, payload_json, simulated_at, recorded_at,
                source_sequence, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                run["id"],
                actor.venue_id,
                signal.source_type,
                signal.source_adapter,
                signal.source_key,
                signal.zone_id,
                signal.signal_type,
                json.dumps(signal.payload, ensure_ascii=False, sort_keys=True),
                simulated_at,
                recorded_at,
                int(sequence["next_sequence"]),
                idempotency_key,
            ),
        )
        await self._record_event(
            actor.venue_id,
            run["id"],
            "SIGNAL_RECORDED",
            "monitoring_signal",
            signal_id,
            {
                "source_type": signal.source_type,
                "source_adapter": signal.source_adapter,
                "zone_id": signal.zone_id,
                "signal_type": signal.signal_type,
                "data": signal.payload,
            },
            simulated_at,
        )
        await self._evaluate_rules(actor.venue_id, run["id"], signal_id, signal, simulated_at)
        row = await self.database.fetch_one(
            "SELECT * FROM scenic_monitoring_signals WHERE id = ?", (signal_id,)
        )
        return _signal_view(row)

    async def _evaluate_rules(self, venue_id, run_id, signal_id, signal, simulated_at):
        if signal.source_type == "DEVICE" and signal.source_key == "vehicle-12":
            active = signal.payload.get("status") == "FAULT"
            await self._set_alert(
                venue_id,
                run_id,
                signal_id,
                signal,
                rule_code="VEHICLE_12_RIGHT_REAR_WHEEL",
                severity="P1",
                title="12 号观光车右后轮异常",
                active=active,
                simulated_at=simulated_at,
            )
        if signal.source_type == "CROWD" and signal.zone_id == "east-gate":
            active = int(signal.payload.get("people", 0)) > int(signal.payload.get("capacity_threshold", 1200))
            await self._set_alert(
                venue_id,
                run_id,
                signal_id,
                signal,
                rule_code="EAST_GATE_CAPACITY",
                severity="P1",
                title="东门客流超过容量阈值",
                active=active,
                simulated_at=simulated_at,
            )

    async def _set_alert(
        self,
        venue_id,
        run_id,
        signal_id,
        signal,
        *,
        rule_code,
        severity,
        title,
        active,
        simulated_at,
    ):
        row = await self.database.fetch_one(
            "SELECT * FROM scenic_situation_alerts WHERE run_id = ? AND rule_code = ? AND source_key = ?",
            (run_id, rule_code, signal.source_key),
        )
        now = time.time()
        if row:
            new_status = "ACTIVE" if active else "RECOVERED"
            if row["status"] == new_status and row["latest_signal_id"] == signal_id:
                return
            await self.database.execute(
                """
                UPDATE scenic_situation_alerts SET status = ?, latest_signal_id = ?,
                    details_json = ?, updated_at = ?, recovered_at = ? WHERE id = ?
                """,
                (
                    new_status,
                    signal_id,
                    json.dumps(signal.payload, ensure_ascii=False, sort_keys=True),
                    now,
                    None if active else now,
                    row["id"],
                ),
            )
            alert_id = row["id"]
            event_type = "ALERT_UPDATED" if active else "ALERT_RECOVERED"
        elif active:
            alert_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{rule_code}:{signal.source_key}"))
            await self.database.execute(
                """
                INSERT INTO scenic_situation_alerts (
                    id, business_id, run_id, venue_id, rule_code, severity,
                    status, zone_id, source_key, title, details_json,
                    first_signal_id, latest_signal_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    build_business_id("GJ", alert_id, now),
                    run_id,
                    venue_id,
                    rule_code,
                    severity,
                    signal.zone_id,
                    signal.source_key,
                    title,
                    json.dumps(signal.payload, ensure_ascii=False, sort_keys=True),
                    signal_id,
                    signal_id,
                    now,
                    now,
                ),
            )
            event_type = "ALERT_CREATED"
        else:
            return
        await self._record_event(
            venue_id,
            run_id,
            event_type,
            "situation_alert",
            alert_id,
            {"rule_code": rule_code, "status": "ACTIVE" if active else "RECOVERED", "severity": severity, "title": title},
            simulated_at,
        )

    async def _transition(self, incident, target, reason, actor_id):
        current = incident["lifecycle"]
        try:
            current_index = _LIFECYCLE_ORDER.index(current)
            target_index = _LIFECYCLE_ORDER.index(target)
        except ValueError as exc:
            raise ScenicCommandConflict("unknown incident lifecycle") from exc
        if target_index != current_index + 1:
            raise ScenicCommandConflict(f"illegal incident transition: {current} -> {target}")
        now = time.time()
        await self.database.execute(
            "UPDATE scenic_incidents SET lifecycle = ?, updated_at = ?, resolved_at = CASE WHEN ? = 'RESOLVED' THEN ? ELSE resolved_at END, closed_at = CASE WHEN ? = 'CLOSED' THEN ? ELSE closed_at END WHERE incident_id = ? AND lifecycle = ?",
            (target, now, target, now, target, now, incident["incident_id"], current),
        )
        await self._record_event(
            incident["venue_id"],
            incident["run_id"],
            "INCIDENT_TRANSITIONED",
            "scenic_incident",
            incident["incident_id"],
            {"from": current, "to": target, "reason": reason, "actor_id": actor_id},
            float(await self._simulation_time(incident["venue_id"])),
        )
        return target

    async def _record_event(self, venue_id, run_id, event_type, resource_type, resource_id, payload, simulated_at):
        event_id = uuid.uuid4().hex
        recorded_at = time.time()
        await self.database.execute(
            """
            INSERT INTO scenic_situation_events (
                event_id, venue_id, run_id, event_type, resource_type,
                resource_id, payload_json, simulated_at, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, venue_id, run_id, event_type, resource_type, resource_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), simulated_at, recorded_at),
        )
        row = await self.database.fetch_one(
            "SELECT * FROM scenic_situation_events WHERE event_id = ?", (event_id,)
        )
        event = _event_view(row)
        if self.publisher:
            await self.publisher(event)
        return event

    async def _audit(self, actor, action, resource_type, resource_id, trace_id):
        await self.database.execute(
            """
            INSERT INTO audit_logs (
                venue_id, user_id, action, resource_type, resource_id,
                outcome, trace_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'SUCCEEDED', ?, ?, ?)
            """,
            (actor.venue_id, actor.user_id, action, resource_type, resource_id, trace_id, json.dumps({"simulated_at": await self._simulation_time(actor.venue_id)}, ensure_ascii=False), time.time()),
        )

    async def _simulation_time(self, venue_id):
        run = await self._current_run(venue_id, required=False)
        return float(run["simulated_at"]) if run else None

    async def _current_run(self, venue_id, *, required=True):
        row = await self.database.fetch_one(
            "SELECT * FROM scenic_simulation_runs WHERE venue_id = ? ORDER BY created_at DESC LIMIT 1",
            (venue_id,),
        )
        if required and not row:
            raise ScenicCommandConflict("no scenic scenario has been prepared")
        return row

    async def incident_view(self, actor: Actor, incident_id: str) -> dict[str, Any]:
        """Read-only incident projection for the Agent trunk entry point."""

        incident = await self._incident(actor.venue_id, incident_id)
        return await self._incident_view(incident)

    async def _incident(self, venue_id, incident_id):
        row = await self.database.fetch_one(
            "SELECT * FROM scenic_incidents WHERE venue_id = ? AND incident_id = ?",
            (venue_id, incident_id),
        )
        if not row:
            raise ScenicCommandConflict("scenic incident was not found")
        return row

    async def _incident_view(self, row, *, alerts=None):
        tasks = await self.database.fetch_all(
            "SELECT * FROM tasks WHERE venue_id = ? AND event_id = ? ORDER BY created_at",
            (row["venue_id"], row["event_id"]),
        )
        approvals = await self.database.fetch_all(
            "SELECT * FROM approval_requests WHERE venue_id = ? AND event_id = ? ORDER BY requested_at",
            (row["venue_id"], row["event_id"]),
        )
        evidence = await self.database.fetch_all(
            "SELECT * FROM scenic_event_evidence WHERE venue_id = ? AND incident_id = ? ORDER BY recorded_at",
            (row["venue_id"], row["incident_id"]),
        )
        hits = await self.database.fetch_all(
            "SELECT * FROM scenic_knowledge_hits WHERE venue_id = ? AND incident_id = ? ORDER BY recorded_at",
            (row["venue_id"], row["incident_id"]),
        )
        notifications = await self.database.fetch_all(
            "SELECT * FROM scenic_notification_receipts WHERE venue_id = ? AND incident_id = ? ORDER BY delivered_at",
            (row["venue_id"], row["incident_id"]),
        )
        activities = await self.database.fetch_all(
            """
            SELECT * FROM event_activities
            WHERE venue_id = ? AND event_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (row["venue_id"], row["event_id"]),
        )
        advice = project_advice(activities)
        if advice and advice.get("trace_id"):
            calls = await self.database.fetch_all(
                """
                SELECT provider, model_name, status, total_tokens, latency_seconds,
                       trace_id, is_mock
                FROM llm_call_logs
                WHERE venue_id = ? AND trace_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (row["venue_id"], advice["trace_id"]),
            )
            advice["model_evidence"] = [
                {
                    "provider": call.get("provider"),
                    "model_name": call.get("model_name"),
                    "status": call.get("status"),
                    "total_tokens": call.get("total_tokens"),
                    "latency_seconds": call.get("latency_seconds"),
                    "trace_id": call.get("trace_id"),
                    "is_mock": bool(call.get("is_mock")),
                }
                for call in calls
            ]
        incident = {
            **row,
            "tasks": [_decode_fields(item, "dependencies", "result", "result_schema_json", "evidence_refs_json") for item in tasks],
            "approvals": [_decode_fields(item, "args", "evidence_snapshot_json", "execution_result") for item in approvals],
            "evidence": evidence,
            "knowledge_hits": hits,
            "notifications": [_decode_fields(item, "result_json") for item in notifications],
            "advice": advice,
        }
        incident["next_actions"] = build_next_actions(
            run={"id": row.get("run_id")},
            alerts=list(alerts or []),
            incident=incident,
            advice=advice,
        )
        return incident

    @staticmethod
    def _require_roles(actor, *roles):
        if actor.role not in roles:
            raise ScenicPermissionDenied("current role is not allowed to execute this command")

    @staticmethod
    def _require_operations(actor):
        if actor.role != "admin" or actor.username != "simulation-ops":
            raise ScenicPermissionDenied("only the protected simulation-ops identity may control inputs")

    @staticmethod
    def _empty_snapshot(venue_id):
        return {
            "venue_id": venue_id,
            "run": None,
            "signals": [],
            "alerts": [],
            "incidents": [],
            "next_actions": build_next_actions(run=None, alerts=[], incident=None, advice=None),
            "advice": None,
            "latest_sequence": 0,
            "map": {
                "adapter": "OFFLINE_SVG",
                "coordinate_system": "LOCAL_SCENIC_GRID_V1",
                "zones": list(_ZONES),
                "routes": [],
                "gis_connector": {"status": "OPTIONAL_CONNECTION / NOT_CONFIGURED", "interface": "ScenicMapAdapter/v1"},
            },
        }


def _json_object(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    decoded = json.loads(value)
    return decoded if isinstance(decoded, dict) else {}


def _run_view(row):
    return {key: row.get(key) for key in ("id", "scenario_key", "scenario_version", "status", "speed", "simulated_at", "started_simulated_at", "created_at", "updated_at")}


def _signal_view(row):
    return {**row, "payload": _json_object(row.get("payload_json"))}


def _alert_view(row):
    return {**row, "details": _json_object(row.get("details_json"))}


def _event_view(row):
    return {
        "sequence": int(row["sequence"]),
        "venue_id": row["venue_id"],
        "event_id": row["event_id"],
        "event_type": row["event_type"],
        "resource_type": row["resource_type"],
        "resource_id": row.get("resource_id"),
        "payload": _json_object(row.get("payload_json")),
        "simulated_at": row.get("simulated_at"),
        "recorded_at": row["recorded_at"],
    }


def _decode_fields(row, *fields):
    result = dict(row)
    for field in fields:
        if field in result and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except json.JSONDecodeError:
                pass
    return result
