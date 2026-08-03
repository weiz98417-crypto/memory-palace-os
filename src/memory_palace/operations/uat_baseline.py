"""Read-only UAT master-data and business-process baseline snapshots."""

from __future__ import annotations

import time
from typing import Any, cast

from ..core.controlled_action_policy import controlled_action_policy_snapshot


_PROCESS_COUNT_QUERIES = {
    "sessions": "SELECT COUNT(*) AS count FROM sessions WHERE venue_id = ?",
    "channel_conversations": "SELECT COUNT(*) AS count FROM channel_conversations WHERE venue_id = ?",
    "messages": """
        SELECT COUNT(*) AS count
        FROM messages message
        JOIN sessions session ON session.session_id = message.session_id
        WHERE session.venue_id = ?
    """,
    "conversation_turns": """
        SELECT COUNT(*) AS count
        FROM conversation_turns turn
        JOIN sessions session ON session.session_id = turn.session_id
        WHERE session.venue_id = ?
    """,
    "message_runs": "SELECT COUNT(*) AS count FROM message_runs WHERE venue_id = ?",
    "message_attachments": "SELECT COUNT(*) AS count FROM message_attachments WHERE venue_id = ?",
    "message_attachment_links": "SELECT COUNT(*) AS count FROM message_attachment_links WHERE venue_id = ?",
    "events": "SELECT COUNT(*) AS count FROM confirmed_events WHERE venue_id = ?",
    "event_activities": "SELECT COUNT(*) AS count FROM event_activities WHERE venue_id = ?",
    "tasks": "SELECT COUNT(*) AS count FROM tasks WHERE venue_id = ?",
    "task_decompositions": "SELECT COUNT(*) AS count FROM task_decompositions WHERE venue_id = ?",
    "approvals": "SELECT COUNT(*) AS count FROM approval_requests WHERE venue_id = ?",
    "push_logs": "SELECT COUNT(*) AS count FROM push_logs WHERE venue_id = ?",
    "tool_invocations": "SELECT COUNT(*) AS count FROM tool_invocation_logs WHERE venue_id = ?",
    "personas": "SELECT COUNT(*) AS count FROM personas WHERE venue_id = ?",
    "persona_interviews": "SELECT COUNT(*) AS count FROM persona_interviews WHERE venue_id = ?",
    "non_sop_knowledge_documents": """
        SELECT COUNT(*) AS count
        FROM knowledge_documents
        WHERE venue_id = ? AND (source_type IS NULL OR source_type <> 'SOP')
    """,
    "knowledge_retrieval_snapshots": "SELECT COUNT(*) AS count FROM knowledge_retrieval_snapshots WHERE venue_id = ?",
    "watcher_policies": "SELECT COUNT(*) AS count FROM watcher_policies WHERE venue_id = ?",
    "watcher_runs": "SELECT COUNT(*) AS count FROM watcher_runs WHERE venue_id = ?",
    "watcher_findings": "SELECT COUNT(*) AS count FROM watcher_findings WHERE venue_id = ?",
    "experience_candidates": "SELECT COUNT(*) AS count FROM experience_candidates WHERE venue_id = ?",
    "experience_candidate_attempts": "SELECT COUNT(*) AS count FROM experience_candidate_attempts WHERE venue_id = ?",
    "experience_interviews": "SELECT COUNT(*) AS count FROM experience_interviews WHERE venue_id = ?",
    "experience_interview_turns": "SELECT COUNT(*) AS count FROM experience_interview_turns WHERE venue_id = ?",
    "experience_interview_authorizations": "SELECT COUNT(*) AS count FROM experience_interview_authorizations WHERE venue_id = ?",
    "experience_cards": "SELECT COUNT(*) AS count FROM experience_cards WHERE venue_id = ?",
    "experience_card_versions": "SELECT COUNT(*) AS count FROM experience_card_versions WHERE venue_id = ?",
    "experience_authorizations": "SELECT COUNT(*) AS count FROM experience_authorizations WHERE venue_id = ?",
    "experience_reviews": "SELECT COUNT(*) AS count FROM experience_reviews WHERE venue_id = ?",
    "experience_usage_logs": "SELECT COUNT(*) AS count FROM experience_usage_logs WHERE venue_id = ?",
    "llm_call_logs": "SELECT COUNT(*) AS count FROM llm_call_logs WHERE venue_id = ?",
    "runtime_recovery_runs": "SELECT COUNT(*) AS count FROM runtime_recovery_runs WHERE venue_id = ?",
}


def approval_rule_snapshot() -> list[dict[str, Any]]:
    """Return the same controlled-action policies consumed by runtime."""

    return cast(list[dict[str, Any]], controlled_action_policy_snapshot())


async def collect_uat_baseline_snapshot(db: Any, *, venue_id: str) -> dict[str, Any]:
    """Collect one sanitized baseline from a consistent read-only snapshot."""

    async with db.read_snapshot() as snapshot:
        return await _collect_uat_baseline_snapshot(
            snapshot,
            venue_id=venue_id,
            captured_at=time.time(),
        )


async def _collect_uat_baseline_snapshot(
    db: Any,
    *,
    venue_id: str,
    captured_at: float,
) -> dict[str, Any]:

    venue = await db.fetch_one(
        "SELECT id, name, status, created_at, updated_at FROM venues WHERE id = ?",
        (venue_id,),
    )
    settings = await db.fetch_all(
        """
        SELECT setting_key, setting_value, value_type, updated_at
        FROM system_settings
        WHERE venue_id = ? AND setting_key IN ('organization_name', 'timezone')
        ORDER BY setting_key
        """,
        (venue_id,),
    )
    setting_values = {row["setting_key"]: row["setting_value"] for row in settings}
    users = await db.fetch_all(
        """
        SELECT id, username, display_name, role, venue_id, department,
               job_title, status, created_at, updated_at
        FROM users
        WHERE venue_id = ?
        ORDER BY role, username
        """,
        (venue_id,),
    )
    identities = await db.fetch_all(
        """
        SELECT id, venue_id, channel, external_tenant_id, external_user_id,
               user_id, status, created_at, updated_at
        FROM channel_identities
        WHERE venue_id = ? AND channel = 'WECOM_SIMULATOR'
        ORDER BY external_tenant_id, external_user_id
        """,
        (venue_id,),
    )
    sops = await db.fetch_all(
        """
        SELECT id, title, version, status, category, priority, source_event_id,
               reviewed_by, published_at, updated_at
        FROM sop_documents
        WHERE venue_id = ? AND status = 'PUBLISHED'
        ORDER BY title, version
        """,
        (venue_id,),
    )
    experts = await db.fetch_all(
        """
        SELECT id, business_id, user_id, display_name, job_title, department,
               years_experience, authorization_status, authorization_signed_at,
               status, updated_at
        FROM expert_profiles
        WHERE venue_id = ? AND authorization_status = 'SIGNED'
        ORDER BY display_name, id
        """,
        (venue_id,),
    )

    process_counts: dict[str, int] = {}
    process_counts.update(await _collect_process_counts(db, venue_id=venue_id))

    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "identity_channel": "WECOM_SIMULATOR",
            "real_wecom_enabled": False,
        },
        "scope": {
            "organization_name": setting_values.get("organization_name"),
            "timezone": setting_values.get("timezone", "Asia/Shanghai"),
            "venue": venue,
        },
        "master_data": {
            "users": users,
            "simulator_identities": identities,
            "published_sops": sops,
            "signed_experts": experts,
            "approval_rules": approval_rule_snapshot(),
        },
        "process_counts": process_counts,
    }


async def collect_uat_pristine_snapshot(
    db: Any,
    *,
    venue_id: str,
) -> dict[str, Any] | None:
    """Collect venue existence and journey counts from one PostgreSQL snapshot."""

    async with db.read_snapshot() as snapshot:
        venue = await snapshot.fetch_one(
            "SELECT id FROM venues WHERE id = ?",
            (venue_id,),
        )
        if venue is None:
            return None
        process_counts = await _collect_process_counts(snapshot, venue_id=venue_id)
        return {
            "venue_id": venue_id,
            "pristine": not any(process_counts.values()),
            "process_counts": process_counts,
        }


async def _collect_process_counts(db: Any, *, venue_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, sql in _PROCESS_COUNT_QUERIES.items():
        row = await db.fetch_one(sql, (venue_id,)) or {}
        counts[name] = int(row.get("count") or 0)
    return counts
