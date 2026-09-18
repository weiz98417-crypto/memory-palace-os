"""Backend-owned next actions and advice projection for the scenic UI."""

from __future__ import annotations

import json
from typing import Any


def _decode(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _decision_allowed(status: str, evidence_status: str | None) -> list[str]:
    if status == "PENDING":
        return ["PROCEED_WITHOUT_WAITING"]
    if status == "FAILED":
        return ["PROCEED_WITHOUT_WAITING"]
    if status == "SUPERSEDED":
        return []
    if status == "READY" and evidence_status == "GROUNDED":
        return ["ADOPT", "IGNORE"]
    if status == "READY" and evidence_status == "NO_EVIDENCE":
        return ["IGNORE", "PROCEED_WITHOUT_WAITING"]
    return []


def project_advice(activities: list[dict[str, Any]]) -> dict[str, Any] | None:
    runs: dict[str, list[dict[str, Any]]] = {}
    for row in activities:
        activity_type = str(row.get("activity_type") or "")
        if not activity_type.startswith("ADVICE_"):
            continue
        payload = _decode(row.get("payload_json"))
        declared_run_id = str(payload.get("advice_run_id") or payload.get("run_id") or "")
        group_key = str(row.get("trace_id") or declared_run_id or row.get("id") or "")
        if not group_key:
            continue
        runs.setdefault(group_key, []).append({**row, "payload": payload, "declared_run_id": declared_run_id})

    if not runs:
        return None

    group_key, rows = max(
        runs.items(),
        key=lambda item: max(float(row.get("created_at") or 0) for row in item[1]),
    )
    run_id = next(
        (row["declared_run_id"] for row in rows if row.get("declared_run_id")),
        group_key,
    )
    rows.sort(key=lambda row: (float(row.get("created_at") or 0), str(row.get("id") or "")))

    status = "PENDING"
    evidence_status: str | None = None
    advice_text: str | None = None
    citations: list[dict[str, Any]] = []
    call_refs: list[str] = []
    trace_id: str | None = None
    decision: dict[str, Any] | None = None
    superseded_by: str | None = None
    failure: dict[str, Any] | None = None

    for row in rows:
        activity_type = str(row["activity_type"])
        payload = row["payload"]
        if activity_type == "ADVICE_PENDING":
            status = str(payload.get("state") or "PENDING")
        elif activity_type == "ADVICE_READY":
            status = str(payload.get("state") or "READY")
            evidence_status = str(payload.get("evidence_status") or "GROUNDED")
            advice_text = str(payload.get("advice") or payload.get("summary") or "")
            citations = list(payload.get("citations") or [])
            call_refs = [str(item) for item in payload.get("call_refs") or []]
            trace_id = str(row.get("trace_id") or "") or None
        elif activity_type == "ADVICE_FAILED":
            status = "FAILED"
            evidence_status = "RETRIEVAL_FAILED"
            failure = {
                "code": payload.get("error_code") or "MODEL_UNAVAILABLE",
                "message": payload.get("error_message") or "未获得模型建议",
            }
        elif activity_type == "ADVICE_DECIDED":
            decision = {
                "decision": payload.get("decision"),
                "reason_code": payload.get("reason_code"),
                "reason_text": payload.get("reason_text"),
                "decided_by": payload.get("decided_by"),
                "decided_at": payload.get("decided_at") or row.get("created_at"),
            }
        elif activity_type == "ADVICE_SUPERSEDED":
            status = "SUPERSEDED"
            superseded_by = str(payload.get("superseded_by") or "SYSTEM")
            decision = {
                "decision": payload.get("decision") or "PROCEED_WITHOUT_WAITING",
                "reason_code": payload.get("reason_code"),
                "reason_text": payload.get("reason_text"),
                "decided_by": payload.get("decided_by"),
                "decided_at": payload.get("decided_at") or row.get("created_at"),
            }

    if status == "PENDING" and decision:
        status = "SUPERSEDED" if decision["decision"] == "PROCEED_WITHOUT_WAITING" else status

    display_status = {
        "PENDING": "分析中",
        "READY": "已就绪",
        "FAILED": "未获得模型建议",
        "SUPERSEDED": "已过期",
    }.get(status, "状态待确认")

    return {
        "run_id": run_id,
        "status": status,
        "display_status": display_status,
        "evidence_status": evidence_status,
        "advice": advice_text,
        "citations": citations,
        "call_refs": call_refs,
        "model_evidence": [],
        "trace_id": trace_id,
        "decision": decision,
        "allowed_actions": [] if decision else _decision_allowed(status, evidence_status),
        "superseded_by": superseded_by,
        "failure": failure,
    }


def _action(
    code: str,
    label: str,
    description: str,
    *,
    action_type: str = "INFO",
    kind: str | None = None,
    payload: dict[str, Any] | None = None,
    view: str | None = None,
    event_id: str | None = None,
    incident_id: str | None = None,
    prerequisites: list[str] | None = None,
    role_required: list[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    action: dict[str, Any] = {"type": action_type}
    if kind:
        action["kind"] = kind
    if payload:
        action["payload"] = payload
    if view:
        action["view"] = view
    if event_id:
        action["event_id"] = event_id
    return {
        "code": code,
        "label": label,
        "description": description,
        "enabled": enabled,
        "prerequisites": prerequisites or [],
        "role_required": role_required or [],
        "incident_id": incident_id,
        "action": action,
    }


def build_next_actions(
    *,
    run: dict[str, Any] | None,
    alerts: list[dict[str, Any]],
    incident: dict[str, Any] | None,
    advice: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not run:
        return [
            _action(
                "WAIT_FOR_SCENARIO",
                "等待运行准备",
                "请由受保护的本地运行准备入口载入版本化故事；业务工作台不提供模拟控制。",
                role_required=["admin"],
            )
        ]

    equipment = next(
        (
            alert
            for alert in alerts
            if alert.get("rule_code") == "VEHICLE_12_RIGHT_REAR_WHEEL" and alert.get("status") == "ACTIVE"
        ),
        None,
    )
    crowd = next(
        (
            alert
            for alert in alerts
            if alert.get("rule_code") == "EAST_GATE_CAPACITY" and alert.get("status") == "ACTIVE"
        ),
        None,
    )

    if equipment and not incident:
        return [
            _action(
                "CONVERT_ALERT",
                "确认设备告警并转为 P1 运营事件",
                "12 号观光车右后轮异常已越过规则阈值，需要建立人工负责的处置卷宗。",
                action_type="COMMAND",
                kind="CONVERT_ALERT",
                payload={"alert_ids": [equipment["id"]]},
                role_required=["manager", "admin"],
            )
        ]

    if not incident:
        return [
            _action(
                "OBSERVE_SITUATION",
                "持续观察态势",
                "当前没有需要建立运营事件的主动告警。",
            )
        ]

    incident_id = str(incident.get("incident_id") or "")
    lifecycle = str(incident.get("lifecycle") or "DETECTED")

    if not (incident.get("evidence") or []):
        return [
            _action(
                "ADD_FIELD_EVIDENCE",
                "补充现场证据",
                "请现场员工提交文字说明、图片或附件。",
                role_required=["operator", "manager", "admin"],
            )
        ]
    if not (incident.get("knowledge_hits") or []):
        return [
            _action(
                "RETRIEVE_SOP",
                "检索雨后复运 SOP",
                "现场证据已收到，检索将经过 PostgreSQL pgvector 与已核验知识链路。",
                action_type="COMMAND",
                kind="RETRIEVE_SOP",
                payload={
                    "incident_id": incident_id,
                    "query": "雨后观光车复运检查和客流分流",
                },
                role_required=["manager", "admin"],
            )
        ]

    if lifecycle in {"DETECTED", "TRIAGED"}:
        if not advice or advice["status"] in {"PENDING", "FAILED"}:
            return [
                _action(
                    "WAIT_FOR_ADVICE",
                    "等待模型建议",
                    "建议正在生成；失败时可以通过建议卡明确选择不等待。",
                    incident_id=incident_id,
                )
            ]
        if advice["status"] == "READY" and not advice.get("decision"):
            return [
                _action(
                    "REVIEW_ADVICE",
                    "查看并判断处置建议",
                    "请核对引用和现场证据后，选择采纳或填写理由忽略。",
                    incident_id=incident_id,
                    role_required=["manager", "admin"],
                )
            ]
        return [
            _action(
                "CREATE_REPAIR_TASK",
                "生成检修任务与高风险审批",
                "任务将派给现场检修人员；继续停运和启用备用车必须由值班经理审批。",
                action_type="COMMAND",
                kind="CREATE_REPAIR_TASK",
                payload={"incident_id": incident_id},
                incident_id=incident_id,
                role_required=["manager", "admin"],
            )
        ]

    if lifecycle == "DISPATCHED":
        return [
            _action(
                "APPROVE_HIGH_RISK",
                "审批并等待现场接单",
                "请批准停运与备用车决策，再由现场员工开始任务。",
                action_type="NAVIGATE",
                view="approvals",
                incident_id=incident_id,
                role_required=["manager", "admin"],
            )
        ]
    if lifecycle == "ACKNOWLEDGED":
        return [
            _action(
                "WAIT_FIELD_RESULT",
                "等待现场检查结果",
                "现场员工已接单，请等待结构化检查结论。",
                incident_id=incident_id,
            )
        ]
    if lifecycle == "MITIGATING" and crowd and not incident.get("diversion_task_id"):
        return [
            _action(
                "CREATE_DIVERSION_TASK",
                "追加东门分流任务",
                "客流超过区域容量阈值，需要为现场补充分流任务。",
                action_type="COMMAND",
                kind="CREATE_DIVERSION_TASK",
                payload={"incident_id": incident_id},
                incident_id=incident_id,
                role_required=["manager", "admin"],
            )
        ]
    if lifecycle == "MITIGATING":
        return [
            _action(
                "RESOLVE_INCIDENT",
                "核验并解除风险",
                "完成任务回执并等待告警恢复后，提交风险解除。",
                action_type="COMMAND",
                kind="RESOLVE_INCIDENT",
                payload={"incident_id": incident_id},
                incident_id=incident_id,
                role_required=["manager", "admin"],
            )
        ]
    if lifecycle == "RESOLVED":
        return [
            _action(
                "CLOSE_INCIDENT",
                "授权关闭事件",
                "关闭门禁仍需校验现场证据、SOP、任务、审批和告警恢复。",
                action_type="COMMAND",
                kind="CLOSE_INCIDENT",
                payload={"incident_id": incident_id},
                incident_id=incident_id,
                role_required=["manager", "admin"],
            )
        ]
    if lifecycle == "CLOSED":
        return [
            _action(
                "VIEW_DOSSIER",
                "查看事件卷宗",
                "审计卷宗和闭环案例已写入 PostgreSQL。",
                action_type="OPEN_DOSSIER",
                event_id=str(incident.get("event_id") or ""),
                incident_id=incident_id,
            )
        ]
    return []
