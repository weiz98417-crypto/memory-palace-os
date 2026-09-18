"""Tenant-scoped trace timeline aggregation for the formal client."""

from __future__ import annotations

import json
from typing import Any, Optional

from src.memory_palace.knowledge.evidence_backed_retrieval import (
    EvidenceBackedKnowledgeRetriever,
)
from src.memory_palace.core.sensitive_output import (
    public_error_message,
    public_record,
    sanitize_public_value,
)


def _decode_json(value: Any) -> Any:
    if value in (None, ""):
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _timeline_item(
    kind: str,
    status: str,
    created_at: Optional[float],
    summary: str,
    *,
    resource_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": status,
        "created_at": created_at,
        "summary": summary,
        "resource_id": resource_id,
        "agent_id": agent_id,
    }


async def build_trace_timeline(
    db: Any,
    *,
    venue_id: str,
    trace_id: str,
    technical: bool = False,
) -> Optional[dict[str, Any]]:
    """Return all durable evidence for one trace without crossing the tenant seam."""

    message_run = await db.fetch_one(
        "SELECT * FROM message_runs WHERE venue_id = ? AND trace_id = ?",
        (venue_id, trace_id),
    )
    model_calls = await db.fetch_all(
        "SELECT * FROM llm_call_logs WHERE venue_id = ? AND trace_id = ? ORDER BY created_at",
        (venue_id, trace_id),
    )
    audit_logs = await db.fetch_all(
        "SELECT * FROM audit_logs WHERE venue_id = ? AND trace_id = ? ORDER BY created_at",
        (venue_id, trace_id),
    )
    events = await db.fetch_all(
        "SELECT * FROM confirmed_events WHERE venue_id = ? AND trace_id = ? ORDER BY created_at",
        (venue_id, trace_id),
    )
    watcher_runs = await db.fetch_all(
        "SELECT * FROM watcher_runs WHERE venue_id = ? AND trace_id = ? ORDER BY started_at",
        (venue_id, trace_id),
    )
    push_logs = await db.fetch_all(
        "SELECT * FROM push_logs WHERE venue_id = ? AND trace_id = ? ORDER BY pushed_at",
        (venue_id, trace_id),
    )
    approvals = await db.fetch_all(
        """
        SELECT * FROM approval_requests
        WHERE venue_id = ? AND correlation_trace_id = ?
        ORDER BY requested_at
        """,
        (venue_id, trace_id),
    )
    tool_invocations = await db.fetch_all(
        """
        SELECT * FROM tool_invocation_logs
        WHERE venue_id = ? AND trace_id = ?
        ORDER BY logged_at
        """,
        (venue_id, trace_id),
    )
    retrievals = await EvidenceBackedKnowledgeRetriever(database=db).list_for_trace(
        venue_id=venue_id,
        trace_id=trace_id,
        technical=technical,
    )
    experience_usage_collection_degraded = False
    try:
        experience_usage_rows = await db.fetch_all(
            """
            SELECT
                usage.*,
                card.business_id,
                card.title,
                card.source_event_id,
                expert.display_name AS expert_name,
                source_event.business_id AS source_event_business_id
            FROM experience_usage_logs usage
            JOIN experience_cards card
              ON card.id = usage.card_id
             AND card.venue_id = usage.venue_id
            JOIN expert_profiles expert
              ON expert.id = card.expert_id
             AND expert.venue_id = card.venue_id
            LEFT JOIN confirmed_events source_event
              ON source_event.event_id = card.source_event_id
             AND source_event.venue_id = card.venue_id
            WHERE usage.venue_id = ? AND usage.trace_id = ?
            ORDER BY usage.created_at
            """,
            (venue_id, trace_id),
        )
    except Exception:
        experience_usage_collection_degraded = True
        experience_usage_rows = []
    experience_usages = [
        _experience_usage_view(row, technical=technical)
        for row in experience_usage_rows
    ]

    if not any(
        (
            message_run,
            model_calls,
            audit_logs,
            events,
            watcher_runs,
            push_logs,
            approvals,
            tool_invocations,
            retrievals,
            experience_usages,
        )
    ):
        return None

    tasks: list[dict[str, Any]] = []
    task_ids = sorted(
        {
            row.get("resource_id")
            for row in audit_logs
            if row.get("resource_type") == "task" and row.get("resource_id")
        }
    )
    if task_ids:
        placeholders = ", ".join("?" for _ in task_ids)
        tasks = await db.fetch_all(
            f"SELECT * FROM tasks WHERE venue_id = ? AND id IN ({placeholders}) ORDER BY created_at",
            (venue_id, *task_ids),
        )

    timeline: list[dict[str, Any]] = []
    if message_run:
        timeline.append(
            _timeline_item(
                "MESSAGE",
                message_run.get("status", "UNKNOWN"),
                message_run.get("created_at"),
                message_run.get("content", "消息已受理"),
                resource_id=message_run.get("message_id"),
                agent_id=message_run.get("target_agent"),
            )
        )
    for model_call in model_calls:
        model_name = model_call.get("model_name") or "deepseek-flash"
        timeline.append(
            _timeline_item(
                "MODEL",
                model_call.get("status", "UNKNOWN"),
                model_call.get("created_at"),
                f"{model_name} 模型调用",
                resource_id=model_call.get("request_id") or model_call.get("id"),
                agent_id=model_call.get("agent_id") or model_call.get("agent_name"),
            )
        )
    for retrieval in retrievals:
        selected_count = int(retrieval.get("selected_count") or 0)
        timeline.append(
            _timeline_item(
                "KNOWLEDGE_RETRIEVAL",
                retrieval.get("status", "UNKNOWN"),
                retrieval.get("started_at"),
                f"知识检索已确权 {selected_count} 条引用",
                resource_id=retrieval.get("id"),
                agent_id=retrieval.get("agent_id") or "MemoryOps",
            )
        )
    for usage in experience_usages:
        timeline.append(
            _timeline_item(
                "EXPERIENCE_USAGE",
                usage.get("usage_type", "REFERENCED"),
                usage.get("created_at"),
                (
                    f"引用专家经验《{usage.get('title') or '未命名经验'}》"
                    f" v{usage.get('version') or '未知'} · "
                    f"{usage.get('expert_name') or '来源专家待确认'}"
                ),
                resource_id=usage.get("business_id"),
                agent_id=usage.get("agent_id") or "Persona",
            )
        )
    for audit_log in audit_logs:
        timeline.append(
            _timeline_item(
                "AUDIT",
                audit_log.get("outcome", "UNKNOWN"),
                audit_log.get("created_at"),
                audit_log.get("action", "审计记录"),
                resource_id=audit_log.get("resource_id"),
                agent_id=_decode_json(audit_log.get("metadata_json")).get("agent"),
            )
        )
    for event in events:
        timeline.append(
            _timeline_item(
                "EVENT",
                event.get("status", "OPEN"),
                event.get("created_at"),
                event.get("raw_text", "事件已落库"),
                resource_id=event.get("event_id"),
            )
        )
    for task in tasks:
        timeline.append(
            _timeline_item(
                "TASK",
                task.get("status", "PENDING"),
                task.get("created_at"),
                task.get("description", "任务已创建"),
                resource_id=task.get("id"),
                agent_id=task.get("assigned_agent"),
            )
        )
    for approval in approvals:
        timeline.append(
            _timeline_item(
                "APPROVAL",
                approval.get("status", "PENDING"),
                approval.get("requested_at"),
                approval.get("tool_name", "受控动作审批"),
                resource_id=approval.get("approval_id"),
            )
        )
    for invocation in tool_invocations:
        timeline.append(
            _timeline_item(
                "TOOL",
                "LOGGED",
                invocation.get("logged_at"),
                invocation.get("tool_name", "工具调用"),
                resource_id=invocation.get("approval_id") or str(invocation.get("id") or ""),
                agent_id=invocation.get("agent_name"),
            )
        )
    for watcher_run in watcher_runs:
        timeline.append(
            _timeline_item(
                "WATCHER",
                watcher_run.get("status", "UNKNOWN"),
                watcher_run.get("started_at"),
                watcher_run.get("summary") or "Watcher 巡检",
                resource_id=watcher_run.get("id"),
                agent_id="watcher",
            )
        )
    for push_log in push_logs:
        push_status = (
            push_log.get("delivery_status", "RECORDED")
            if str(push_log.get("channel") or "").upper().endswith("_REPLY")
            else push_log.get("adoption_status", "pending")
        )
        timeline.append(
            _timeline_item(
                "PUSH",
                str(push_status).upper(),
                push_log.get("pushed_at"),
                push_log.get("raw_text", "推送动作"),
                resource_id=push_log.get("push_id"),
            )
        )
    if experience_usage_collection_degraded:
        timeline.append(
            _timeline_item(
                "EVIDENCE_COLLECTION",
                "DEGRADED",
                message_run.get("updated_at") if message_run else None,
                "经验引用证据暂时无法读取，当前追踪记录不完整",
                agent_id="Persona",
            )
        )

    timeline.sort(key=lambda item: (item.get("created_at") is None, item.get("created_at") or 0))
    statuses = {str(item.get("status", "")).upper() for item in timeline}
    if statuses & {
        "FAILED",
        "ERROR",
        "EXECUTION_FAILED",
        "CONFIGURATION_REQUIRED",
        "RETRY_REQUIRED",
        "DEAD_LETTERED",
    }:
        overall_status = "FAILED"
    elif statuses & {
        "PENDING",
        "RUNNING",
        "ACCEPTED",
        "QUEUED",
        "PROCESSING",
        "RECOVERING",
        "RETRYING",
    }:
        overall_status = "RUNNING"
    elif "DEGRADED" in statuses:
        overall_status = "DEGRADED"
    else:
        overall_status = "SUCCEEDED"

    if message_run:
        stored_message_run = dict(message_run)
        decoded_result = _decode_json(stored_message_run.get("result_json", "{}"))
        public_fields = (
            "message_id",
            "trace_id",
            "session_id",
            "user_id",
            "venue_id",
            "content",
            "status",
            "channel",
            "external_message_id",
            "external_conversation_id",
            "reply_text",
            "created_at",
            "updated_at",
            "processed_at",
        )
        if technical:
            public_fields = (*public_fields, "target_agent")
        message_run = public_record(stored_message_run, public_fields)
        message_run["result"] = (
            sanitize_public_value(decoded_result)
            if technical
            else _business_message_result(decoded_result)
        )
        if stored_message_run.get("error"):
            message_run["error_summary"] = public_error_message(
                stored_message_run.get("error")
            )

    return sanitize_public_value({
        "trace_id": trace_id,
        "venue_id": venue_id,
        "status": overall_status,
        "message_run": message_run,
        "summary": {
            "model_calls": len(model_calls),
            "audits": len(audit_logs),
            "events": len(events),
            "tasks": len(tasks),
            "approvals": len(approvals),
            "tool_invocations": len(tool_invocations),
            "watcher_runs": len(watcher_runs),
            "push_logs": len(push_logs),
            "knowledge_retrievals": len(retrievals),
            "knowledge_hits": sum(
                int(retrieval.get("selected_count") or 0) for retrieval in retrievals
            ),
            "experience_usages": len(experience_usages),
        },
        "retrievals": retrievals,
        "experience_usages": experience_usages,
        "timeline": timeline,
    })


def _experience_usage_view(
    row: dict[str, Any],
    *,
    technical: bool,
) -> dict[str, Any]:
    view = {
        "business_id": row.get("business_id"),
        "title": row.get("title"),
        "expert_name": row.get("expert_name"),
        "version": row.get("experience_version"),
        "usage_type": row.get("usage_type"),
        "score": row.get("score"),
        "source_event_business_id": row.get("source_event_business_id"),
        "created_at": row.get("created_at"),
        "agent_id": row.get("agent_id") or "Persona",
    }
    if technical:
        view.update(
            {
                "id": row.get("id"),
                "card_id": row.get("card_id"),
                "user_id": row.get("user_id"),
                "session_id": row.get("session_id"),
                "message_id": row.get("message_id"),
                "trace_id": row.get("trace_id"),
                "retrieval_snapshot_id": row.get("retrieval_snapshot_id"),
                "query_text": sanitize_public_value(row.get("query_text")),
            }
        )
    return view


def _business_message_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_card_fields = {
        "card_type",
        "business_code",
        "title",
        "summary",
        "severity",
        "severity_label",
        "status",
        "owner_name",
        "next_action",
        "recommended_action",
        "risk_reason",
        "required_tools",
        "immediate_actions",
        "source_type",
        "source_name",
        "source_title",
        "version",
        "version_label",
        "expert_name",
        "publisher_name",
        "published_at",
        "relevance",
        "source_event_business_id",
        "applicable_context",
        "authorization_scopes",
    }
    cards = value.get("business_cards") or []
    business_cards = [
        {
            key: sanitize_public_value(card[key])
            for key in allowed_card_fields
            if key in card
        }
        for card in cards
        if isinstance(card, dict)
    ]
    return {
        "reply_text": sanitize_public_value(value.get("reply_text")),
        "business_cards": business_cards,
    }
