"""Read-only UAT master-data and business-process baseline snapshots."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any


_APPROVAL_RULES = (
    {
        "code": "SUSPEND_PASSENGER_VEHICLE",
        "name": "停运载客车辆",
        "approval_required": True,
        "approver_roles": ["manager"],
        "execution_mode": "MANAGER_DECISION",
    },
    {
        "code": "ACTIVATE_BACKUP_VEHICLE",
        "name": "启用备用车辆",
        "approval_required": True,
        "approver_roles": ["manager"],
        "execution_mode": "MANAGER_DECISION",
    },
    {
        "code": "SEND_CRITICAL_DISPATCH_ALERT",
        "name": "向调度群发送严重告警",
        "approval_required": True,
        "approver_roles": ["manager"],
        "execution_mode": "CONTROLLED_TOOL",
        "tool_name": "send_in_app_alert",
        "delivery_channel": "WECOM_SIMULATOR_OUTBOX",
    },
)

_PROCESS_COUNT_QUERIES = {
    "sessions": "SELECT COUNT(*) AS count FROM sessions WHERE venue_id = ?",
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
    "events": "SELECT COUNT(*) AS count FROM confirmed_events WHERE venue_id = ?",
    "event_activities": "SELECT COUNT(*) AS count FROM event_activities WHERE venue_id = ?",
    "tasks": "SELECT COUNT(*) AS count FROM tasks WHERE venue_id = ?",
    "task_decompositions": "SELECT COUNT(*) AS count FROM task_decompositions WHERE venue_id = ?",
    "approvals": "SELECT COUNT(*) AS count FROM approval_requests WHERE venue_id = ?",
    "push_logs": "SELECT COUNT(*) AS count FROM push_logs WHERE venue_id = ?",
    "tool_invocations": "SELECT COUNT(*) AS count FROM tool_invocation_logs WHERE venue_id = ?",
    "watcher_runs": "SELECT COUNT(*) AS count FROM watcher_runs WHERE venue_id = ?",
    "watcher_findings": "SELECT COUNT(*) AS count FROM watcher_findings WHERE venue_id = ?",
    "experience_candidates": "SELECT COUNT(*) AS count FROM experience_candidates WHERE venue_id = ?",
    "experience_interviews": "SELECT COUNT(*) AS count FROM experience_interviews WHERE venue_id = ?",
    "experience_cards": "SELECT COUNT(*) AS count FROM experience_cards WHERE venue_id = ?",
}


def approval_rule_snapshot() -> list[dict[str, Any]]:
    """Return a caller-safe copy of the frozen UAT approval policy."""

    return deepcopy(list(_APPROVAL_RULES))


async def collect_uat_baseline_snapshot(db: Any, *, venue_id: str) -> dict[str, Any]:
    """Collect a sanitized baseline using read-only database queries."""

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
    for name, sql in _PROCESS_COUNT_QUERIES.items():
        row = await db.fetch_one(sql, (venue_id,)) or {}
        process_counts[name] = int(row.get("count") or 0)

    return {
        "schema_version": 1,
        "captured_at": time.time(),
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
