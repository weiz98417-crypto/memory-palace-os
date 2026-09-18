"""Persistent Watcher policy execution shared by API and scheduler."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any, Optional

from loguru import logger

from ..skills.watcher import WatcherSkill
from .event_closure import calculate_event_closure_conditions
from .sensitive_output import public_error_message, sanitize_public_value


EVENT_WATCHER_MODEL = "deepseek-flash"
_EVENT_POLICY_NAMESPACE = uuid.UUID("684ef953-2a28-47cc-8ddb-490b20918b46")


class WatcherRunFailed(RuntimeError):
    def __init__(self, message: str, *, run_id: str, trace_id: str):
        super().__init__(message)
        self.run_id = run_id
        self.trace_id = trace_id


async def recover_interrupted_watcher_runs(db: Any) -> int:
    """Finalize process-scoped runs left RUNNING by an earlier process."""
    interrupted = await db.fetch_all(
        "SELECT id, venue_id FROM watcher_runs WHERE status = 'RUNNING'",
    )
    if not interrupted:
        return 0
    recovered = 0
    for run in interrupted:
        finalized = await _fail_watcher_run(
            db,
            run_id=run["id"],
            venue_id=run["venue_id"],
            error="Watcher run interrupted by application restart",
        )
        recovered += int(finalized)
    logger.warning("Recovered {} interrupted Watcher run(s)", recovered)
    return recovered


async def _fail_watcher_run(
    db: Any,
    *,
    run_id: str,
    venue_id: str,
    error: str,
) -> bool:
    try:
        removed_findings = await db.execute(
            """
            DELETE FROM watcher_findings
            WHERE run_id = ? AND venue_id = ? AND status = 'OPEN'
            """,
            (run_id, venue_id),
        )
        if removed_findings:
            logger.warning(
                "Discarded {} OPEN finding(s) from failed Watcher run {}",
                removed_findings,
                run_id,
            )
    except Exception as exc:
        logger.error(
            "Failed to discard OPEN findings for Watcher run {} ({})",
            run_id,
            type(exc).__name__,
        )

    try:
        updated = await db.execute(
            """
            UPDATE watcher_runs
            SET status = 'FAILED', error = ?, completed_at = ?
            WHERE id = ? AND venue_id = ? AND status = 'RUNNING'
            """,
            (error[:2000], time.time(), run_id, venue_id),
        )
        return updated == 1
    except Exception as exc:
        logger.error(
            "Failed to persist FAILED status for Watcher run {} ({})",
            run_id,
            type(exc).__name__,
        )
        return False


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def _sanitize_event_watcher_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        section: sanitize_public_value(value)
        for section, value in snapshot.items()
    }
    raw_notifications = snapshot.get("notifications")
    public_notifications = sanitized.get("notifications")
    if isinstance(raw_notifications, list) and isinstance(public_notifications, list):
        for raw_notification, public_notification in zip(
            raw_notifications,
            public_notifications,
        ):
            if not isinstance(raw_notification, dict) or not isinstance(public_notification, dict):
                continue
            if "delivery_error" in raw_notification:
                public_notification["delivery_error"] = sanitize_public_value(
                    raw_notification.get("delivery_error")
                )
    return sanitized


def _decoded_row(row: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for source, default in fields.items():
        target = source.removesuffix("_json")
        decoded[target] = _json_value(decoded.pop(source, None), default)
    return decoded


async def _fetch_related_rows(
    db: Any,
    *,
    table: str,
    venue_id: str,
    filters: list[tuple[str, set[str]]],
    order_by: str,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = [venue_id]
    for column, values in filters:
        normalized = sorted(value for value in values if value)
        if not normalized:
            continue
        placeholders = ",".join("?" for _ in normalized)
        clauses.append(f"{column} IN ({placeholders})")
        params.extend(normalized)
    if not clauses:
        return []
    return await db.fetch_all(
        f"SELECT * FROM {table} WHERE venue_id = ? AND ({' OR '.join(clauses)}) ORDER BY {order_by}",
        tuple(params),
    )


def _unique_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value and value not in unique:
            unique[value] = row
    return list(unique.values())


async def collect_event_watcher_snapshot(
    db: Any,
    *,
    venue_id: str,
    event_id: str,
) -> dict[str, Any]:
    """Persistable evidence bundle used by the event closure Watcher."""
    event = await db.fetch_one(
        "SELECT * FROM confirmed_events WHERE venue_id = ? AND event_id = ?",
        (venue_id, event_id),
    )
    if not event:
        raise LookupError("Event not found")

    activities = await db.fetch_all(
        """
        SELECT * FROM event_activities
        WHERE venue_id = ? AND event_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (venue_id, event_id),
    )
    message_ids = {
        str(value)
        for value in (
            event.get("push_id"),
            *(activity.get("message_id") for activity in activities),
        )
        if value
    }
    session_ids = {
        str(activity["session_id"])
        for activity in activities
        if activity.get("session_id")
    }
    messages = await _fetch_related_rows(
        db,
        table="message_runs",
        venue_id=venue_id,
        filters=[("message_id", message_ids), ("session_id", session_ids)],
        order_by="created_at ASC, message_id ASC",
    )
    session_ids.update(
        str(message["session_id"])
        for message in messages
        if message.get("session_id")
    )
    if session_ids:
        messages.extend(
            await _fetch_related_rows(
                db,
                table="message_runs",
                venue_id=venue_id,
                filters=[("session_id", session_ids)],
                order_by="created_at ASC, message_id ASC",
            )
        )
    messages = sorted(
        _unique_rows(messages, "message_id"),
        key=lambda row: (float(row.get("created_at") or 0), str(row.get("message_id") or "")),
    )
    message_ids.update(
        str(message["message_id"])
        for message in messages
        if message.get("message_id")
    )

    tasks = await db.fetch_all(
        """
        SELECT * FROM tasks
        WHERE venue_id = ? AND event_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (venue_id, event_id),
    )
    approvals = await db.fetch_all(
        """
        SELECT * FROM approval_requests
        WHERE venue_id = ? AND event_id = ?
        ORDER BY requested_at ASC, approval_id ASC
        """,
        (venue_id, event_id),
    )
    trace_ids = {
        str(value)
        for value in (
            event.get("trace_id"),
            *(activity.get("trace_id") for activity in activities),
            *(message.get("trace_id") for message in messages),
            *(approval.get("correlation_trace_id") for approval in approvals),
            *(approval.get("execution_trace_id") for approval in approvals),
        )
        if value
    }
    retrievals = await _fetch_related_rows(
        db,
        table="knowledge_retrieval_snapshots",
        venue_id=venue_id,
        filters=[
            ("trace_id", trace_ids),
            ("message_id", message_ids),
            ("session_id", session_ids),
        ],
        order_by="started_at ASC, id ASC",
    )
    notifications = await _fetch_related_rows(
        db,
        table="push_logs",
        venue_id=venue_id,
        filters=[
            ("push_id", {str(event.get("push_id") or "")}),
            ("msg_id", message_ids),
            ("trace_id", trace_ids),
        ],
        order_by="pushed_at ASC, id ASC",
    )

    decoded_messages = [
        _decoded_row(message, {"result_json": {}})
        for message in messages
    ]
    decoded_tasks = [
        _decoded_row(
            task,
            {
                "dependencies": [],
                "result_schema_json": {},
                "evidence_refs_json": [],
                "result": {},
            },
        )
        for task in tasks
    ]
    decoded_approvals = [
        _decoded_row(
            approval,
            {
                "args": {},
                "evidence_snapshot_json": {},
                "execution_result": {},
            },
        )
        for approval in approvals
    ]
    decoded_retrievals = [
        _decoded_row(
            retrieval,
            {
                "filter_json": {},
                "attempts_json": [],
                "references_json": [],
            },
        )
        for retrieval in retrievals
    ]
    references: list[dict[str, Any]] = []
    seen_references: set[tuple[str, str, str]] = set()
    for retrieval in decoded_retrievals:
        for reference in retrieval.get("references", []):
            if not isinstance(reference, dict):
                continue
            reference_key = (
                str(reference.get("source_type") or ""),
                str(reference.get("resource_id") or reference.get("source_id") or ""),
                str(reference.get("version") or ""),
            )
            if reference_key in seen_references:
                continue
            seen_references.add(reference_key)
            references.append(reference)

    closure_conditions = await calculate_event_closure_conditions(
        db,
        venue_id=venue_id,
        event_id=event_id,
        tasks=tasks,
        approvals=approvals,
    )
    captured_at = time.time()
    started_at = event.get("created_at") or event.get("confirmed_at") or captured_at
    ended_at = event.get("closed_at") or captured_at
    elapsed_seconds = max(0, int(float(ended_at) - float(started_at)))
    severity = str(event.get("severity") or "P3").upper()
    sla_minutes = {"P0": 3, "P1": 10, "P2": 30, "P3": 120, "P4": 120}.get(severity, 120)
    event_snapshot = _decoded_row(event, {"context_trigger_data": {}})
    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "event": event_snapshot,
        "messages": decoded_messages,
        "knowledge_references": references,
        "knowledge_retrievals": decoded_retrievals,
        "tasks": decoded_tasks,
        "approvals": decoded_approvals,
        "notifications": [
            _decoded_row(notification, {"hit_keywords": []})
            for notification in notifications
        ],
        "handling": {
            "started_at": started_at,
            "ended_at": ended_at,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_minutes": elapsed_seconds // 60,
            "sla_minutes": sla_minutes,
            "sla_overdue": (
                str(event.get("status") or "OPEN").upper() != "CLOSED"
                and elapsed_seconds > sla_minutes * 60
            ),
        },
        "closure_conditions": closure_conditions,
    }


async def _ensure_event_watcher_policy(
    db: Any,
    *,
    venue_id: str,
    created_by: str,
) -> str:
    policy_id = uuid.uuid5(
        _EVENT_POLICY_NAMESPACE,
        f"event-closure:{venue_id}",
    ).hex
    now = time.time()
    await db.execute(
        """
        INSERT INTO watcher_policies (
            id, venue_id, name, description, schedule_cron, enabled,
            check_types_json, config_json, version, created_by,
            created_at, updated_at
        ) VALUES (?, ?, '事件闭环证据检查', '闭环前聚合并检查事件全量证据',
            '0 0 1 1 *', ?, '["SLA","TASK","SOP"]', '{}', 1, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (policy_id, venue_id, False, created_by, now, now),
    )
    return policy_id


def _event_audit_target(snapshot: dict[str, Any]) -> dict[str, Any]:
    event = snapshot["event"]
    return {
        "case_id": event["event_id"],
        "source_type": "event",
        "severity": event.get("severity") or "P3",
        "dispatched_instruction": json.dumps(
            {
                "event": event,
                "messages": snapshot["messages"],
                "knowledge_references": snapshot["knowledge_references"],
                "tasks": snapshot["tasks"],
                "approvals": snapshot["approvals"],
                "notifications": snapshot["notifications"],
            },
            ensure_ascii=False,
        ),
        "employee_replies": json.dumps(
            {
                "task_results": [task.get("result") for task in snapshot["tasks"]],
                "approval_executions": [
                    approval.get("execution_result")
                    for approval in snapshot["approvals"]
                ],
                "notification_delivery": [
                    notification.get("delivery_status")
                    for notification in snapshot["notifications"]
                ],
            },
            ensure_ascii=False,
        ),
        "elapsed_minutes": snapshot["handling"]["elapsed_minutes"],
        "status": event.get("status") or "OPEN",
    }


def _deterministic_event_issues(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    event = snapshot["event"]
    event_id = str(event["event_id"])
    severity = str(event.get("severity") or "P2").upper()
    issues: list[dict[str, Any]] = []
    for blocker in snapshot["closure_conditions"].get("blockers", []):
        issues.append(
            {
                "case_id": event_id,
                "source_type": blocker.get("resource_type") or "event",
                "source_id": blocker.get("resource_id") or event_id,
                "issue_type": blocker.get("code") or "CLOSURE_BLOCKED",
                "title": "事件闭环条件未满足",
                "violation_reason": blocker.get("message") or "存在未完成的闭环条件。",
                "severity_level": severity,
            }
        )
    for task in snapshot["tasks"]:
        if str(task.get("status") or "").upper() != "DONE":
            continue
        if task.get("result") not in (None, "", {}, []):
            continue
        issues.append(
            {
                "case_id": event_id,
                "source_type": "task",
                "source_id": task.get("id") or event_id,
                "issue_type": "TASK_RESULT_MISSING",
                "title": "任务缺少处置结果",
                "violation_reason": f"已完成任务“{task.get('description') or task.get('business_id') or '未命名任务'}”没有可核验结果。",
                "severity_level": severity,
            }
        )
    for approval in snapshot["approvals"]:
        if str(approval.get("execution_status") or "").upper() != "SUCCEEDED":
            continue
        if approval.get("execution_result") not in (None, "", {}, []):
            continue
        issues.append(
            {
                "case_id": event_id,
                "source_type": "approval",
                "source_id": approval.get("approval_id") or event_id,
                "issue_type": "ACTION_RESULT_MISSING",
                "title": "受控动作缺少执行结果",
                "violation_reason": "受控动作标记为执行成功，但没有保存执行结果。",
                "severity_level": severity,
            }
        )
    for notification in snapshot["notifications"]:
        delivery_status = str(notification.get("delivery_status") or "RECORDED").upper()
        if delivery_status in {"DELIVERED", "PERSISTED", "SENT", "SUCCEEDED"}:
            continue
        if not notification.get("recipient"):
            continue
        issues.append(
            {
                "case_id": event_id,
                "source_type": "notification",
                "source_id": notification.get("push_id") or event_id,
                "issue_type": "NOTIFICATION_DELIVERY_INCOMPLETE",
                "title": "通知尚未确认送达",
                "violation_reason": notification.get("delivery_error")
                or f"通知送达状态为 {delivery_status}。",
                "severity_level": severity,
            }
        )
    if snapshot["handling"].get("sla_overdue"):
        issues.append(
            {
                "case_id": event_id,
                "source_type": "event",
                "source_id": event_id,
                "issue_type": "SLA_EXCEEDED",
                "title": "事件处置已超过 SLA",
                "violation_reason": (
                    f"事件已处置 {snapshot['handling']['elapsed_minutes']} 分钟，"
                    f"超过 {snapshot['handling']['sla_minutes']} 分钟 SLA。"
                ),
                "severity_level": severity,
            }
        )
    return issues


async def run_event_watcher_check(
    db: Any,
    *,
    event_id: str,
    venue_id: str,
    actor_id: str,
) -> dict[str, Any]:
    snapshot = await collect_event_watcher_snapshot(
        db,
        venue_id=venue_id,
        event_id=event_id,
    )
    snapshot = _sanitize_event_watcher_snapshot(snapshot)
    policy_id = await _ensure_event_watcher_policy(
        db,
        venue_id=venue_id,
        created_by=actor_id,
    )
    run_id = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    started_at = time.time()
    snapshot_json = json.dumps(snapshot, ensure_ascii=False)
    await db.execute(
        """
        INSERT INTO watcher_runs (
            id, policy_id, venue_id, event_id, trigger_source, status,
            trace_id, model_name, target_count, finding_count, summary,
            target_snapshot_json, result_json, started_at
        ) VALUES (?, ?, ?, ?, 'EVENT_CLOSURE', 'RUNNING', ?, ?, 1, 0,
            NULL, ?, '{}', ?)
        """,
        (
            run_id,
            policy_id,
            venue_id,
            event_id,
            trace_id,
            EVENT_WATCHER_MODEL,
            snapshot_json,
            started_at,
        ),
    )

    watcher = WatcherSkill()
    watcher.model_name = EVENT_WATCHER_MODEL
    try:
        result = await watcher.run(
            context={
                "trigger_source": "EVENT_CLOSURE",
                "venue_id": venue_id,
                "event_id": event_id,
                "policy_id": policy_id,
                "audit_target_logs": [_event_audit_target(snapshot)],
            },
            trace_id=trace_id,
        )
        if not result.success:
            raise RuntimeError(result.error_msg or "Watcher returned an unsuccessful result")
        sanitized_structured = sanitize_public_value(result.structured_data or {})
        structured = sanitized_structured if isinstance(sanitized_structured, dict) else {}
        escalations = [
            *_deterministic_event_issues(snapshot),
            *(structured.get("escalated_cases") or structured.get("escalations") or []),
        ]
        finding_candidates = [
            _event_finding_from_escalation(
                escalation,
                run_id=run_id,
                policy_id=policy_id,
                venue_id=venue_id,
                event_id=event_id,
            )
            for escalation in escalations
        ]
        findings: list[dict[str, Any]] = []
        seen_issue_keys: set[tuple[str, str, str]] = set()
        for candidate in finding_candidates:
            issue_key = (
                str(candidate["source_type"]),
                str(candidate["source_id"]),
                str(candidate["issue_fingerprint"]),
            )
            if issue_key in seen_issue_keys:
                continue
            seen_issue_keys.add(issue_key)
            findings.append(
                await _persist_or_reuse_finding(db, finding=candidate)
            )
        completed_at = time.time()
        summary = (
            "证据完整，可闭环"
            if not findings
            else "；".join(finding["description"] for finding in findings)
        )
        result_payload = sanitize_public_value({
            "ready_to_close": not findings,
            "issues": findings,
            "model_output": structured,
        })
        await db.execute(
            """
            UPDATE watcher_runs
            SET status = 'SUCCEEDED', finding_count = ?, summary = ?,
                result_json = ?, completed_at = ?
            WHERE id = ? AND venue_id = ?
            """,
            (
                len(findings),
                summary,
                json.dumps(result_payload, ensure_ascii=False),
                completed_at,
                run_id,
                venue_id,
            ),
        )
        await db.execute(
            """
            UPDATE watcher_policies SET last_run_at = ?, updated_at = ?
            WHERE id = ? AND venue_id = ?
            """,
            (completed_at, completed_at, policy_id, venue_id),
        )
    except asyncio.CancelledError:
        await asyncio.shield(
            _fail_watcher_run(
                db,
                run_id=run_id,
                venue_id=venue_id,
                error="Watcher event check cancelled during application shutdown",
            )
        )
        raise
    except Exception as exc:
        public_error = public_error_message(exc, context="operation") or "Watcher operation failed"
        await _fail_watcher_run(
            db,
            run_id=run_id,
            venue_id=venue_id,
            error=public_error,
        )
        logger.error(
            "[Trace-{}] Watcher event check {} failed ({})",
            trace_id,
            event_id,
            type(exc).__name__,
        )
        raise WatcherRunFailed(
            public_error,
            run_id=run_id,
            trace_id=trace_id,
        ) from exc

    run = await db.fetch_one(
        "SELECT * FROM watcher_runs WHERE id = ? AND venue_id = ?",
        (run_id, venue_id),
    )
    run["target_snapshot"] = _json_value(run.pop("target_snapshot_json"), {})
    run["result"] = _json_value(run.pop("result_json"), {})
    return {
        "event_id": event_id,
        "ready_to_close": not findings,
        "summary": summary,
        "model": EVENT_WATCHER_MODEL,
        "run": run,
        "findings": findings,
        "trace_id": trace_id,
    }


async def collect_watcher_targets(
    db: Any,
    *,
    venue_id: str,
    check_types: Optional[list[str]] = None,
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Build the actual audit dataset from open events and unfinished tasks."""
    check_types = check_types or ["SLA", "TASK", "SOP"]
    config = config or {}
    now = time.time()
    targets: list[dict[str, Any]] = []

    if "SLA" in check_types or "SOP" in check_types:
        events = await db.fetch_all(
            """
            SELECT event_id, severity, raw_text, resolution, status,
                   created_at, confirmed_at, updated_at
            FROM confirmed_events
            WHERE venue_id = ? AND COALESCE(status, 'OPEN') != 'CLOSED'
            ORDER BY COALESCE(updated_at, confirmed_at, created_at) ASC
            LIMIT 200
            """,
            (venue_id,),
        )
        for event in events:
            created_at = event.get("created_at") or event.get("confirmed_at") or now
            try:
                elapsed_minutes = max(0, int((now - float(created_at)) / 60))
            except (TypeError, ValueError):
                elapsed_minutes = 0
            targets.append(
                {
                    "case_id": event["event_id"],
                    "source_type": "event",
                    "severity": event.get("severity") or "P2",
                    "dispatched_instruction": event.get("raw_text") or "",
                    "employee_replies": event.get("resolution") or "未反馈",
                    "elapsed_minutes": elapsed_minutes,
                    "status": event.get("status") or "OPEN",
                }
            )

    if "TASK" in check_types:
        tasks = await db.fetch_all(
            """
            SELECT id, description, status, result, error, created_at, updated_at
            FROM tasks
            WHERE venue_id = ? AND status IN ('PENDING', 'RUNNING', 'BLOCKED', 'FAILED')
            ORDER BY updated_at ASC
            LIMIT 200
            """,
            (venue_id,),
        )
        for task in tasks:
            created_at = task.get("created_at") or now
            targets.append(
                {
                    "case_id": task["id"],
                    "source_type": "task",
                    "severity": "P2" if task.get("status") == "FAILED" else "P3",
                    "dispatched_instruction": task.get("description") or "",
                    "employee_replies": task.get("error") or task.get("result") or "未反馈",
                    "elapsed_minutes": max(0, int((now - float(created_at)) / 60)),
                    "status": task.get("status") or "PENDING",
                }
            )

    max_targets = int(config.get("max_targets", 200))
    return targets[: max(1, min(max_targets, 400))]


def _finding_from_escalation(
    escalation: Any,
    *,
    run_id: str,
    policy_id: str,
    venue_id: str,
) -> dict[str, Any]:
    if not isinstance(escalation, dict):
        escalation = {"description": str(escalation)}
    source_id = str(
        escalation.get("source_id")
        or escalation.get("case_id")
        or escalation.get("id")
        or ""
    )
    description = str(
        escalation.get("violation_reason")
        or escalation.get("reason")
        or escalation.get("description")
        or escalation.get("issue")
        or "Watcher 检测到需要人工复核的异常。"
    )
    title = str(escalation.get("title") or escalation.get("issue_type") or "巡检异常")[:200]
    severity = str(
        escalation.get("severity_level")
        or escalation.get("severity")
        or escalation.get("risk_level")
        or "P2"
    ).upper()
    if severity not in {"P0", "P1", "P2", "P3", "P4"}:
        severity = "P2"
    finding = {
        "id": uuid.uuid4().hex,
        "run_id": run_id,
        "policy_id": policy_id,
        "venue_id": venue_id,
        "finding_type": str(escalation.get("issue_type") or escalation.get("type") or "COMPLIANCE")[:80],
        "severity": severity,
        "title": title,
        "description": description[:4000],
        "source_type": escalation.get("source_type") or "event",
        "source_id": source_id or None,
    }
    fingerprint_payload = {
        "finding_type": " ".join(finding["finding_type"].strip().lower().split()),
        "title": " ".join(finding["title"].strip().lower().split()),
        "description": " ".join(finding["description"].strip().lower().split()),
    }
    finding["issue_fingerprint"] = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return finding


def _event_finding_from_escalation(
    escalation: Any,
    *,
    run_id: str,
    policy_id: str,
    venue_id: str,
    event_id: str,
) -> dict[str, Any]:
    finding = _finding_from_escalation(
        escalation,
        run_id=run_id,
        policy_id=policy_id,
        venue_id=venue_id,
    )
    finding["event_id"] = event_id
    return finding


async def _persist_or_reuse_finding(
    db: Any,
    *,
    finding: dict[str, Any],
) -> dict[str, Any]:
    lookup_params = (
        finding["venue_id"],
        finding["policy_id"],
        finding["source_type"],
        finding["source_id"],
        finding["issue_fingerprint"],
    )
    now = time.time()
    await db.execute(
        """
        INSERT INTO watcher_findings (
            id, run_id, policy_id, venue_id, event_id, finding_type,
            severity, title, description, source_type, source_id,
            issue_fingerprint, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            finding["id"],
            finding["run_id"],
            finding["policy_id"],
            finding["venue_id"],
            finding.get("event_id"),
            finding["finding_type"],
            finding["severity"],
            finding["title"],
            finding["description"],
            finding["source_type"],
            finding["source_id"],
            finding["issue_fingerprint"],
            now,
            now,
        ),
    )
    persisted = await db.fetch_one(
        """
        SELECT * FROM watcher_findings
        WHERE venue_id = ? AND policy_id = ? AND source_type = ?
          AND source_id = ? AND issue_fingerprint = ? AND status != 'CLOSED'
        ORDER BY created_at ASC LIMIT 1
        """,
        lookup_params,
    )
    if not persisted:
        raise RuntimeError("Watcher finding could not be persisted")
    reused = persisted["id"] != finding["id"]
    if reused:
        await db.execute(
            """
            UPDATE watcher_findings
            SET severity = ?, title = ?, description = ?, updated_at = ?
            WHERE id = ? AND venue_id = ? AND status != 'CLOSED'
            """,
            (
                finding["severity"],
                finding["title"],
                finding["description"],
                now,
                persisted["id"],
                finding["venue_id"],
            ),
        )
        persisted = await db.fetch_one(
            "SELECT * FROM watcher_findings WHERE id = ? AND venue_id = ?",
            (persisted["id"], finding["venue_id"]),
        )
    persisted["reused"] = reused
    return persisted


async def run_watcher_policy(
    db: Any,
    *,
    policy_id: str,
    venue_id: str,
    trigger_source: str,
) -> dict[str, Any]:
    """Run a persisted Watcher policy and persist run evidence and findings."""
    policy = await db.fetch_one(
        "SELECT * FROM watcher_policies WHERE id = ? AND venue_id = ?",
        (policy_id, venue_id),
    )
    if not policy:
        raise LookupError("Watcher policy not found")
    if not bool(policy.get("enabled")):
        raise RuntimeError("Watcher policy is disabled")

    check_types = _json_value(policy.get("check_types_json"), [])
    config = _json_value(policy.get("config_json"), {})
    targets = await collect_watcher_targets(
        db,
        venue_id=venue_id,
        check_types=check_types,
        config=config,
    )
    targets = [sanitize_public_value(target) for target in targets]
    targets = [target for target in targets if isinstance(target, dict)]
    run_id = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    started_at = time.time()
    await db.execute(
        """
        INSERT INTO watcher_runs (
            id, policy_id, venue_id, trigger_source, status, trace_id,
            target_count, finding_count, result_json, started_at
        ) VALUES (?, ?, ?, ?, 'RUNNING', ?, ?, 0, '{}', ?)
        """,
        (run_id, policy_id, venue_id, trigger_source, trace_id, len(targets), started_at),
    )

    try:
        result = await WatcherSkill().run(
            context={
                "trigger_source": trigger_source,
                "venue_id": venue_id,
                "policy_id": policy_id,
                "policy_config": config,
                "audit_target_logs": targets,
            },
            trace_id=trace_id,
        )
        if not result.success:
            raise RuntimeError(result.error_msg or "Watcher returned an unsuccessful result")
        sanitized_structured = sanitize_public_value(result.structured_data or {})
        structured = sanitized_structured if isinstance(sanitized_structured, dict) else {}
        escalations = structured.get("escalated_cases") or structured.get("escalations") or []
        finding_candidates = [
            _finding_from_escalation(
                escalation,
                run_id=run_id,
                policy_id=policy_id,
                venue_id=venue_id,
            )
            for escalation in escalations
        ]
        findings: list[dict[str, Any]] = []
        seen_issue_keys: set[tuple[str, str, str]] = set()
        for candidate in finding_candidates:
            issue_key = (
                str(candidate["source_type"]),
                str(candidate["source_id"]),
                str(candidate["issue_fingerprint"]),
            )
            if issue_key in seen_issue_keys:
                continue
            seen_issue_keys.add(issue_key)
            findings.append(
                await _persist_or_reuse_finding(db, finding=candidate)
            )
        now = time.time()
        summary = sanitize_public_value(result.reply_text or (
            f"完成 {len(targets)} 条记录巡检，发现 {len(findings)} 项需要处理的问题。"
        ))
        summary = summary if isinstance(summary, str) else "Watcher policy completed"
        await db.execute(
            """
            UPDATE watcher_runs
            SET status = 'SUCCEEDED', finding_count = ?, summary = ?,
                result_json = ?, completed_at = ?
            WHERE id = ? AND venue_id = ?
            """,
            (
                len(findings),
                summary,
                json.dumps(structured, ensure_ascii=False),
                now,
                run_id,
                venue_id,
            ),
        )
        await db.execute(
            "UPDATE watcher_policies SET last_run_at = ?, updated_at = ? WHERE id = ? AND venue_id = ?",
            (now, now, policy_id, venue_id),
        )
        logger.info(
            "[Trace-{}] Watcher policy {} completed with {} findings",
            trace_id,
            policy_id,
            len(findings),
        )
        return {
            "run_id": run_id,
            "trace_id": trace_id,
            "status": "SUCCEEDED",
            "target_count": len(targets),
            "finding_count": len(findings),
            "summary": summary,
            "findings": findings,
            "model": "deepseek-flash" if targets else None,
        }
    except asyncio.CancelledError:
        await asyncio.shield(
            _fail_watcher_run(
                db,
                run_id=run_id,
                venue_id=venue_id,
                error="Watcher run cancelled during application shutdown",
            )
        )
        logger.warning("[Trace-{}] Watcher policy {} cancelled", trace_id, policy_id)
        raise
    except Exception as exc:
        public_error = public_error_message(exc, context="operation") or "Watcher operation failed"
        await _fail_watcher_run(
            db,
            run_id=run_id,
            venue_id=venue_id,
            error=public_error,
        )
        logger.error(
            "[Trace-{}] Watcher policy {} failed ({})",
            trace_id,
            policy_id,
            type(exc).__name__,
        )
        raise
