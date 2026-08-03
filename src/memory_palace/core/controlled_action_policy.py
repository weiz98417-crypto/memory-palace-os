"""Authoritative runtime policies for high-risk controlled actions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class ControlledActionPolicy:
    code: str
    name: str
    approval_required: bool
    approver_roles: tuple[str, ...]
    execution_mode: str
    tool_name: str
    delivery_channel: Optional[str] = None

    def to_public_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["approver_roles"] = list(self.approver_roles)
        return result


_CONTROLLED_ACTION_POLICIES = (
    ControlledActionPolicy(
        code="SUSPEND_PASSENGER_VEHICLE",
        name="停运载客车辆",
        approval_required=True,
        approver_roles=("admin", "manager"),
        execution_mode="MANAGER_DECISION",
        tool_name="record_manager_decision",
    ),
    ControlledActionPolicy(
        code="ACTIVATE_BACKUP_VEHICLE",
        name="启用备用车辆",
        approval_required=True,
        approver_roles=("admin", "manager"),
        execution_mode="MANAGER_DECISION",
        tool_name="record_manager_decision",
    ),
    ControlledActionPolicy(
        code="SEND_CRITICAL_DISPATCH_ALERT",
        name="向调度群发送严重告警",
        approval_required=True,
        approver_roles=("admin", "manager"),
        execution_mode="CONTROLLED_TOOL",
        tool_name="send_in_app_alert",
        delivery_channel="WECOM_SIMULATOR_OUTBOX",
    ),
)

_POLICIES_BY_CODE = {policy.code: policy for policy in _CONTROLLED_ACTION_POLICIES}


def get_controlled_action_policy(code: str) -> Optional[ControlledActionPolicy]:
    return _POLICIES_BY_CODE.get(str(code or "").strip().upper())


def controlled_action_policy_snapshot() -> list[dict[str, object]]:
    return deepcopy([policy.to_public_dict() for policy in _CONTROLLED_ACTION_POLICIES])


def approval_tool_names() -> set[str]:
    return {policy.tool_name for policy in _CONTROLLED_ACTION_POLICIES if policy.approval_required}
