"""Readable controlled-action outbox for the WeCom simulator."""

from __future__ import annotations

import json
from typing import Any

from .sensitive_output import public_error_message, sanitize_public_value


_TOOL_LABELS = {
    "send_alert": "告警广播",
    "send_in_app_alert": "企微模拟器通知",
    "send_sms": "短信通知",
}
_SIMULATOR_DELIVERY_CHANNELS = {"IN_APP", "WECOM_SIMULATOR_OUTBOX"}
_SOURCE_ROLE_LABELS = {
    "EVENT_REPORTER": "事件上报人",
    "EVENT_OWNER": "事件负责人",
    "TASK_ASSIGNEE": "任务负责人",
}


class SimulatorRecipientsNotReady(RuntimeError):
    code = "SIMULATOR_RECIPIENTS_NOT_READY"

    def __init__(self, missing: list[dict[str, Any]]):
        super().__init__("企微模拟器收件人尚未就绪")
        self.missing = missing


def _candidate_label(source_roles: list[str]) -> str:
    return "、".join(
        _SOURCE_ROLE_LABELS.get(role, role)
        for role in source_roles
    )


async def _active_recipient(
    database: Any,
    *,
    venue_id: str,
    user_id: str,
    source_roles: list[str],
    session_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    user = await database.fetch_one(
        """
        SELECT id, display_name, department, job_title, status
        FROM users
        WHERE id = ? AND venue_id = ?
        """,
        (user_id, venue_id),
    )
    source_role_labels = [
        _SOURCE_ROLE_LABELS.get(role, role)
        for role in source_roles
    ]
    if user is None:
        return None, {
            "user_id": user_id,
            "display_name": f"未识别员工（{_candidate_label(source_roles)}）",
            "source_roles": source_roles,
            "source_role_labels": source_role_labels,
            "reason_code": "USER_NOT_IN_TENANT",
            "reason": "未在当前场地找到该业务参与人",
        }
    readable = {
        "user_id": user_id,
        "display_name": user.get("display_name") or user_id,
        "department": user.get("department"),
        "job_title": user.get("job_title"),
        "source_roles": source_roles,
    }
    if str(user.get("status") or "").upper() != "ACTIVE":
        return None, {
            **readable,
            "reason_code": "USER_INACTIVE",
            "reason": "员工账号已停用",
        }

    identity = await database.fetch_one(
        """
        SELECT id
        FROM channel_identities
        WHERE venue_id = ? AND user_id = ?
          AND channel = 'WECOM' AND status = 'ACTIVE'
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (venue_id, user_id),
    )
    if identity is None:
        return None, {
            **readable,
            "reason_code": "WECOM_IDENTITY_INACTIVE",
            "reason": "员工没有可用的企微身份绑定",
        }

    if session_id:
        conversation = await database.fetch_one(
            """
            SELECT c.session_id
            FROM channel_conversations c
            JOIN sessions s
              ON s.session_id = c.session_id AND s.venue_id = c.venue_id
             AND s.user_id = c.user_id
            WHERE c.venue_id = ? AND c.user_id = ? AND c.session_id = ?
              AND c.channel = 'WECOM_SIMULATOR' AND c.status = 'ACTIVE'
            """,
            (venue_id, user_id, session_id),
        )
    else:
        conversation = await database.fetch_one(
            """
            SELECT c.session_id
            FROM channel_conversations c
            JOIN sessions s
              ON s.session_id = c.session_id AND s.venue_id = c.venue_id
             AND s.user_id = c.user_id
            WHERE c.venue_id = ? AND c.user_id = ?
              AND c.channel = 'WECOM_SIMULATOR' AND c.status = 'ACTIVE'
            ORDER BY c.updated_at DESC, c.created_at DESC, c.session_id DESC
            LIMIT 1
            """,
            (venue_id, user_id),
        )
    if conversation is None:
        return None, {
            **readable,
            "reason_code": "SIMULATOR_SESSION_MISSING",
            "reason": "员工尚未开启可用的企微模拟器会话",
        }
    return {
        **readable,
        "session_id": conversation["session_id"],
    }, None


async def build_event_participant_delivery(
    database: Any,
    *,
    venue_id: str,
    event_id: str,
) -> dict[str, Any]:
    """Freeze readable, tenant-safe simulator recipients for one event."""
    event = await database.fetch_one(
        """
        SELECT from_user, assigned_to
        FROM confirmed_events
        WHERE venue_id = ? AND event_id = ?
        """,
        (venue_id, event_id),
    )
    task_rows = await database.fetch_all(
        """
        SELECT assigned_user_id
        FROM tasks
        WHERE venue_id = ? AND event_id = ? AND assigned_user_id IS NOT NULL
        ORDER BY created_at, id
        """,
        (venue_id, event_id),
    )
    candidates: dict[str, list[str]] = {}

    def include(value: Any, role: str) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            return
        roles = candidates.setdefault(normalized, [])
        if role not in roles:
            roles.append(role)

    include((event or {}).get("from_user"), "EVENT_REPORTER")
    include((event or {}).get("assigned_to"), "EVENT_OWNER")
    for task in task_rows:
        include(task.get("assigned_user_id"), "TASK_ASSIGNEE")

    if not candidates:
        raise SimulatorRecipientsNotReady(
            [
                {
                    "display_name": "事件相关人员",
                    "source_roles": [],
                    "source_role_labels": [],
                    "reason_code": "EVENT_PARTICIPANTS_MISSING",
                    "reason": "事件尚未关联可通知的业务参与人",
                }
            ]
        )

    targets: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for user_id, source_roles in candidates.items():
        target, failure = await _active_recipient(
            database,
            venue_id=venue_id,
            user_id=user_id,
            source_roles=source_roles,
        )
        if target is not None:
            targets.append(target)
        if failure is not None:
            missing.append(failure)
    if missing:
        raise SimulatorRecipientsNotReady(missing)
    return {
        "scope": "EVENT_PARTICIPANTS",
        "channel": "WECOM_SIMULATOR_OUTBOX",
        "target_count": len(targets),
        "targets": targets,
    }


async def validate_frozen_simulator_targets(
    database: Any,
    *,
    venue_id: str,
    targets: list[dict[str, Any]],
) -> None:
    """Reject delivery when any frozen target is no longer simulator-safe."""
    missing: list[dict[str, Any]] = []
    for frozen in targets:
        user_id = str(frozen.get("user_id") or "").strip()
        session_id = str(frozen.get("session_id") or "").strip()
        source_roles = frozen.get("source_roles")
        if not isinstance(source_roles, list):
            source_roles = []
        _target, failure = await _active_recipient(
            database,
            venue_id=venue_id,
            user_id=user_id,
            source_roles=[str(role) for role in source_roles],
            session_id=session_id,
        )
        if failure is not None:
            missing.append(failure)
    if missing:
        raise SimulatorRecipientsNotReady(missing)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _public_text(value: Any) -> str | None:
    sanitized = sanitize_public_value(value)
    if sanitized in (None, ""):
        return None
    return str(sanitized)


def _approval_status(approval: dict[str, Any], push: dict[str, Any] | None) -> tuple[str, str]:
    approval_status = str(approval.get("status") or "PENDING").upper()
    execution_status = str(approval.get("execution_status") or "NOT_STARTED").upper()
    delivery_status = str((push or {}).get("delivery_status") or "").upper()

    if approval_status == "PENDING":
        return "PENDING", "等待管理员审批"
    if approval_status == "REJECTED":
        return "REJECTED", "审批已拒绝"
    if execution_status == "FAILED" or delivery_status == "FAILED":
        if delivery_status == "FAILED":
            return "FAILED", "审批通过，但出站送达失败"
        return "FAILED", "审批通过，但动作执行失败"
    if execution_status == "SUCCEEDED":
        if delivery_status == "DELIVERED":
            return "SUCCEEDED", "审批通过，动作已执行并送达"
        return "SUCCEEDED", "审批通过，动作执行成功，尚无模拟器送达记录"
    return "EXECUTING", "审批已通过，动作执行中"


def _push_status(push: dict[str, Any]) -> tuple[str, str]:
    delivery_status = str(push.get("delivery_status") or "RECORDED").upper()
    if delivery_status == "FAILED":
        return "FAILED", "出站送达失败"
    if delivery_status == "DELIVERED":
        return "SUCCEEDED", "出站消息已送达"
    return "EXECUTING", "出站消息处理中"


def _approval_item(
    approval: dict[str, Any],
    push: dict[str, Any] | None,
    supersedes_business_id: str | None,
    session_id: str,
) -> dict[str, Any]:
    args = _json_object(approval.get("args"))
    status, status_summary = _approval_status(approval, push)
    requested_at = float(approval.get("requested_at") or 0)
    reviewed_at = float(approval.get("reviewed_at") or 0)
    pushed_at = float((push or {}).get("pushed_at") or 0)
    tool_name = str(approval.get("tool_name") or "")
    return {
        "id": f"approval:{approval['approval_id']}",
        "kind": "CONTROLLED_ACTION",
        "session_id": session_id,
        "approval_id": str(approval["approval_id"]),
        "business_id": approval.get("business_id"),
        "supersedes_approval_id": approval.get("supersedes_approval_id"),
        "supersedes_business_id": supersedes_business_id,
        "push_id": (push or {}).get("push_id"),
        "event_id": approval.get("event_id"),
        "task_id": approval.get("task_id"),
        "tool_name": tool_name,
        "tool_label": _TOOL_LABELS.get(tool_name, "受控通知"),
        "message": _public_text((push or {}).get("raw_text") or args.get("message")) or "未填写通知内容",
        "status": status,
        "status_summary": status_summary,
        "approval_status": str(approval.get("status") or "PENDING").upper(),
        "execution_status": str(approval.get("execution_status") or "NOT_STARTED").upper(),
        "delivery_status": (
            str(push.get("delivery_status") or "RECORDED").upper() if push else None
        ),
        "review_comment": _public_text(approval.get("comment")),
        "execution_error": public_error_message(
            approval.get("execution_error"),
            context="operation",
        ),
        "delivery_error": public_error_message(
            (push or {}).get("delivery_error"),
            context="operation",
        ),
        "trace_id": (
            approval.get("execution_trace_id")
            or (push or {}).get("trace_id")
            or approval.get("correlation_trace_id")
        ),
        "created_at": requested_at,
        "updated_at": max(requested_at, reviewed_at, pushed_at),
    }


def _orphan_push_item(session_id: str, push: dict[str, Any]) -> dict[str, Any]:
    status, status_summary = _push_status(push)
    pushed_at = float(push.get("pushed_at") or 0)
    return {
        "id": f"push:{push['push_id']}",
        "kind": "OUTBOUND_MESSAGE",
        "session_id": session_id,
        "approval_id": None,
        "business_id": None,
        "push_id": str(push["push_id"]),
        "event_id": None,
        "task_id": None,
        "tool_name": None,
        "tool_label": str(push.get("event_type") or "出站通知"),
        "message": _public_text(push.get("raw_text")) or "未填写通知内容",
        "status": status,
        "status_summary": status_summary,
        "approval_status": None,
        "execution_status": None,
        "delivery_status": str(push.get("delivery_status") or "RECORDED").upper(),
        "review_comment": None,
        "execution_error": None,
        "delivery_error": public_error_message(
            push.get("delivery_error"),
            context="operation",
        ),
        "trace_id": push.get("trace_id"),
        "created_at": pushed_at,
        "updated_at": pushed_at,
    }


async def load_simulator_outbox(
    database: Any,
    *,
    venue_id: str,
    session_id: str,
) -> list[dict[str, Any]]:
    """Return one readable timeline item per approval or unlinked session push."""
    pushes = await database.fetch_all(
        """
        SELECT * FROM push_logs
        WHERE venue_id = ? AND recipient = ?
        ORDER BY pushed_at, push_id
        """,
        (venue_id, f"session:{session_id}"),
    )
    simulator_pushes = [
        push
        for push in pushes
        if str(push.get("channel") or "").upper() in _SIMULATOR_DELIVERY_CHANNELS
    ]
    linked_approval_ids = {
        str(push.get("msg_id") or "").strip()
        for push in simulator_pushes
        if str(push.get("msg_id") or "").strip()
    }
    candidate_approvals = await database.fetch_all(
        """
        SELECT * FROM approval_requests
        WHERE venue_id = ?
        ORDER BY requested_at, approval_id
        """,
        (venue_id,),
    )
    approvals = []
    for approval in candidate_approvals:
        approval_id = str(approval["approval_id"])
        evidence = _json_object(approval.get("evidence_snapshot_json"))
        delivery = evidence.get("delivery")
        if not isinstance(delivery, dict):
            delivery = {}
        is_fanout = (
            str(delivery.get("scope") or "").upper() == "EVENT_PARTICIPANTS"
            and isinstance(delivery.get("targets"), list)
        )
        if is_fanout:
            frozen_session_ids = {
                str(target.get("session_id") or "").strip()
                for target in delivery["targets"]
                if isinstance(target, dict)
            }
            if session_id not in frozen_session_ids:
                continue
        elif (
            str(approval.get("session_id") or "") != session_id
            and approval_id not in linked_approval_ids
        ):
            continue
        approvals.append(approval)

    approval_ids = {str(approval["approval_id"]) for approval in approvals}
    approval_business_ids = {
        str(approval["approval_id"]): approval.get("business_id")
        for approval in approvals
    }
    pushes_by_approval: dict[str, dict[str, Any]] = {}
    orphan_pushes: list[dict[str, Any]] = []
    for push in simulator_pushes:
        linked_approval_id = next(
            (
                value
                for value in (
                    str(push.get("msg_id") or ""),
                    str(push.get("idempotency_key") or ""),
                )
                if value in approval_ids
            ),
            None,
        )
        if linked_approval_id:
            existing = pushes_by_approval.get(linked_approval_id)
            if existing is None or float(push.get("pushed_at") or 0) >= float(
                existing.get("pushed_at") or 0
            ):
                pushes_by_approval[linked_approval_id] = push
            continue
        if push.get("recipient") == f"session:{session_id}":
            orphan_pushes.append(push)

    items = [
        _approval_item(
            approval,
            pushes_by_approval.get(str(approval["approval_id"])),
            approval_business_ids.get(
                str(approval.get("supersedes_approval_id") or "")
            ),
            session_id,
        )
        for approval in approvals
    ]
    items.extend(_orphan_push_item(session_id, push) for push in orphan_pushes)
    return sorted(items, key=lambda item: (item["created_at"], item["id"]))
