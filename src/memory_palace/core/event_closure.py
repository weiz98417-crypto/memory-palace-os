from __future__ import annotations

import time
from typing import Any


def _resource_label(row: dict[str, Any], fallback: str) -> str:
    return str(row.get("business_id") or fallback)


async def calculate_event_closure_conditions(
    database,
    *,
    venue_id: str,
    event_id: str,
    tasks: list[dict[str, Any]] | None = None,
    approvals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if tasks is None:
        tasks = await database.fetch_all(
            """
            SELECT id, business_id, description, status, error, block_reason
            FROM tasks
            WHERE venue_id = ? AND event_id = ?
            ORDER BY created_at ASC
            """,
            (venue_id, event_id),
        )
    if approvals is None:
        approvals = await database.fetch_all(
            """
            SELECT approval_id, business_id, tool_name, task_id, status,
                   execution_status, execution_error, supersedes_approval_id
            FROM approval_requests
            WHERE venue_id = ? AND event_id = ?
            ORDER BY requested_at ASC
            """,
            (venue_id, event_id),
        )

    blockers: list[dict[str, Any]] = []
    for task in tasks:
        task_status = str(task.get("status") or "PENDING").upper()
        if task_status == "DONE":
            continue
        task_label = _resource_label(task, "未编号任务")
        blockers.append(
            {
                "code": "UNFINISHED_TASK",
                "message": f"仍有未完成任务：{task.get('description') or task_label}",
                "resource_type": "task",
                "resource_id": task.get("id"),
                "business_id": task.get("business_id"),
                "status": task_status,
            }
        )

    superseded_approval_ids = {
        str(approval["supersedes_approval_id"])
        for approval in approvals
        if approval.get("supersedes_approval_id")
    }
    for approval in approvals:
        approval_status = str(approval.get("status") or "PENDING").upper()
        execution_status = str(
            approval.get("execution_status") or "NOT_STARTED"
        ).upper()
        approval_id = str(approval.get("approval_id") or "")
        approval_label = _resource_label(approval, "未编号审批")

        if approval_status == "PENDING":
            blockers.append(
                {
                    "code": "PENDING_APPROVAL",
                    "message": f"仍有待处理审批：{approval_label}",
                    "resource_type": "approval",
                    "resource_id": approval_id,
                    "business_id": approval.get("business_id"),
                    "status": approval_status,
                    "execution_status": execution_status,
                }
            )
            continue

        if approval_status == "APPROVED" and execution_status != "SUCCEEDED":
            failed = execution_status == "FAILED"
            blockers.append(
                {
                    "code": (
                        "ACTION_EXECUTION_FAILED"
                        if failed
                        else "ACTION_EXECUTION_INCOMPLETE"
                    ),
                    "message": (
                        f"已批准动作执行失败：{approval_label}"
                        if failed
                        else f"已批准动作尚未执行完成：{approval_label}"
                    ),
                    "resource_type": "approval",
                    "resource_id": approval_id,
                    "business_id": approval.get("business_id"),
                    "status": approval_status,
                    "execution_status": execution_status,
                    "execution_error": approval.get("execution_error"),
                }
            )
            continue

        if approval_status == "REJECTED" and approval_id not in superseded_approval_ids:
            blockers.append(
                {
                    "code": "UNRESOLVED_REJECTION",
                    "message": f"被拒绝的动作尚未重新提交：{approval_label}",
                    "resource_type": "approval",
                    "resource_id": approval_id,
                    "business_id": approval.get("business_id"),
                    "status": approval_status,
                    "execution_status": execution_status,
                }
            )

    blocker_counts: dict[str, int] = {}
    for blocker in blockers:
        blocker_counts[blocker["code"]] = blocker_counts.get(blocker["code"], 0) + 1

    return {
        "ready": not blockers,
        "checked_at": time.time(),
        "task_count": len(tasks),
        "approval_count": len(approvals),
        "blocker_count": len(blockers),
        "blocker_counts": blocker_counts,
        "blockers": blockers,
    }
