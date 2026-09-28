"""Expand the scenic demo dataset through formal HTTP APIs only.

The script deliberately mixes two formal sources:

* repeated scenic simulation runs for operational events, and
* the admin historical-event intake for event-type coverage.

Tasks and approvals are then created through the existing task/permission APIs.
No business table is written directly, and the permission engine's high-risk
approval cooldown remains in force.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = PROJECT_ROOT / "artifacts" / "scenic-e2e" / "bulk-enrichment.json"


class EnrichmentError(RuntimeError):
    """Raised when a formal API step does not complete."""


@dataclass(frozen=True)
class HistoricalTemplate:
    event_type: str
    severity: str
    summary: str
    place: str
    task_focus: str


HISTORICAL_TEMPLATES = (
    HistoricalTemplate(
        "客流拥堵",
        "P1",
        "排队区客流持续上升并越过第二道隔离线，现场需要增开通道并保护消防通道。",
        "东门外广场",
        "疏导排队客流并复核消防通道净宽",
    ),
    HistoricalTemplate(
        "设备异常",
        "P1",
        "观光车雨后复检出现轮端异响和制动跑偏，车辆已暂停使用并等待设备组确认。",
        "观光车检修区",
        "复核轮端制动状态并完成空载试车记录",
    ),
    HistoricalTemplate(
        "运营中断",
        "P0",
        "索道上站短时停电，轿厢暂停运行，站务正在安抚乘客并确认故障范围。",
        "索道上站",
        "确认故障范围并同步乘客疏导安排",
    ),
    HistoricalTemplate(
        "食品安全",
        "P1",
        "餐饮街出现疑似同批次食品投诉，游客已前往医务室，需要立即封存留样和销售凭证。",
        "餐饮街",
        "封存同批次食品并核对销售记录",
    ),
    HistoricalTemplate(
        "安全隐患",
        "P2",
        "闭园复核发现设备夹层检修门未上锁，现场存在临时工具和无关人员进入风险。",
        "设备夹层",
        "完成门禁复核并补齐双人签退记录",
    ),
    HistoricalTemplate(
        "游客求助",
        "P1",
        "游客服务中心接报儿童走散，已取得衣着特征和最近照片，需要同步门岗与监控巡查。",
        "中心湖游客中心",
        "调取沿线监控并通知门岗联动查找",
    ),
    HistoricalTemplate(
        "复盘改进",
        "P2",
        "事件复盘材料已汇总，但经验草稿缺少反例、责任边界和原始证据引用，暂不具备发布条件。",
        "运营标准部",
        "补齐经验证据和边界条件后提交审核",
    ),
    HistoricalTemplate(
        "协同异常",
        "P2",
        "高峰调度期间公共频道重复询问较多，位置和任务责任人描述不一致，影响跨部门确认。",
        "指挥调度中心",
        "统一播报格式并复核关键指令接收情况",
    ),
    HistoricalTemplate(
        "客流预警",
        "P2",
        "北门落客区预计短时集中到达多支团队，需要在车辆到达前完成批次和集合点预排。",
        "北门落客区",
        "预排团队批次并准备备用落客区",
    ),
    HistoricalTemplate(
        "消防安全",
        "P1",
        "消防通道巡检发现临时物料占用通道，现场需要立即清理并核对责任区域。",
        "西区商业街",
        "清理通道障碍并复核消防设施状态",
    ),
    HistoricalTemplate(
        "气象灾害",
        "P0",
        "短时强降雨导致低洼路段积水，部分户外项目受到影响，需要同步疏散和道路管控。",
        "山林步道",
        "完成积水路段管控和游客疏散",
    ),
    HistoricalTemplate(
        "医疗救援",
        "P1",
        "游客在观景平台出现胸闷和乏力，现场医护已到场，需要开辟通道并持续更新家属联络。",
        "山顶观景平台",
        "协助医疗转运并保持单一联络窗口",
    ),
    HistoricalTemplate(
        "服务投诉",
        "P3",
        "游客对排队时长和现场提示不清晰提出投诉，需要核对服务过程并给出可追踪回应。",
        "南门检票区",
        "核对现场服务记录并回访游客诉求",
    ),
    HistoricalTemplate(
        "环境卫生",
        "P3",
        "餐饮区垃圾清运频次不足，垃圾桶外溢并产生异味，需要立即清理并调整清运计划。",
        "餐饮区",
        "完成重点区域清理并增加巡检频次",
    ),
    HistoricalTemplate(
        "运营管理",
        "P2",
        "交接班记录缺少未完成任务截止时间和下一责任人，接班人员无法确认后续处置边界。",
        "值班经理室",
        "补齐交接信息并确认下一班责任人",
    ),
)


@dataclass
class CreatedTask:
    task_id: str
    event_id: str
    session_id: str
    assigned_user_id: str
    status: str
    dependency_blocked: bool = False


class FormalAPI:
    def __init__(self, base_url: str, password: str) -> None:
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=90.0)
        self.password = password
        self.tokens: dict[str, str] = {}

    def close(self) -> None:
        self.http.close()

    def login(self, username: str) -> dict[str, Any]:
        response = self.http.post(
            "/api/v1/auth/login", json={"username": username, "password": self.password}
        )
        if response.status_code >= 400:
            raise EnrichmentError(
                f"login failed for {username}: {response.status_code} {response.text[:240]}"
            )
        payload = response.json()
        self.tokens[username] = payload["access_token"]
        return payload["user"]

    def request(
        self,
        method: str,
        path: str,
        *,
        username: str | None = None,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        allowed: tuple[int, ...] = (200, 201, 202),
    ) -> Any:
        headers: dict[str, str] = {}
        if username:
            headers["Authorization"] = f"Bearer {self.tokens[username]}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:128]
        response = self.http.request(method, path, json=body, headers=headers)
        if response.status_code not in allowed:
            raise EnrichmentError(
                f"{method} {path} failed: {response.status_code} {response.text[:500]}"
            )
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def get(self, path: str, username: str) -> Any:
        return self.request("GET", path, username=username)

    def post(
        self,
        path: str,
        username: str,
        body: dict[str, Any] | None = None,
        *,
        key: str | None = None,
    ) -> Any:
        return self.request(
            "POST", path, username=username, body=body, idempotency_key=key
        )

    def patch(self, path: str, username: str, body: dict[str, Any]) -> Any:
        return self.request("PATCH", path, username=username, body=body)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"[:128]


def _items(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get(key, [])
    else:
        value = payload
    return value if isinstance(value, list) else []


def _counts(
    api: FormalAPI, manager: str, cycle_count: int, historical_count: int
) -> dict[str, int]:
    del cycle_count, historical_count
    events = _items(api.get("/api/v1/admin/events?limit=500", manager), "events")
    tasks = _items(api.get("/api/v1/admin/tasks?limit=500", manager), "tasks")
    approvals = _items(
        api.get("/api/v1/admin/approvals?status=ALL", manager), "approvals"
    )
    pushes = _items(api.get("/api/v1/admin/push_logs?limit=500", manager), "push_logs")
    knowledge = _items(
        api.get("/api/v1/admin/knowledge?limit=500", manager), "knowledge"
    )
    experience = _items(
        api.get("/api/v1/admin/experience-cards?limit=500", manager), "experience_cards"
    )
    findings = _items(
        api.get("/api/v1/admin/watcher/findings?limit=500", manager), "findings"
    )
    sops = _items(api.get("/api/v1/admin/sops", manager), "sops")
    return {
        "events": len(events),
        "tasks": len(tasks),
        "approvals": len(approvals),
        "push_logs": len(pushes),
        "knowledge": len(knowledge),
        "experience_cards": len(experience),
        "watcher_findings": len(findings),
        "sops": len(sops),
    }


def _create_simulated_event(
    api: FormalAPI, index: int, assignee: dict[str, Any]
) -> dict[str, str]:
    prepared = api.post(
        "/api/v1/operations/scenic/commands",
        "simulation-ops",
        {
            "kind": "PREPARE_SCENARIO",
            "payload": {"scenario_key": "rain_vehicle_east_gate"},
        },
        key=_id(f"bulk-prepare-{index}"),
    )
    api.post(
        "/api/v1/operations/scenic/commands",
        "simulation-ops",
        {"kind": "CLOCK_STEP", "payload": {"seconds": 2}},
        key=_id(f"bulk-step-{index}"),
    )
    snapshot = api.get("/api/v1/scenic/snapshot", "wangfang")
    alert = next(
        (
            item
            for item in snapshot.get("alerts", [])
            if item.get("rule_code") == "VEHICLE_12_RIGHT_REAR_WHEEL"
        ),
        None,
    )
    if not alert:
        raise EnrichmentError(
            f"simulation run {prepared.get('run_id')} produced no vehicle alert"
        )
    converted = api.post(
        "/api/v1/scenic/commands",
        "wangfang",
        {"kind": "CONVERT_ALERT", "payload": {"alert_ids": [alert["id"]]}},
        key=_id(f"bulk-convert-{index}"),
    )
    event_id = str(converted["event_id"])
    api.patch(
        f"/api/v1/admin/events/{event_id}",
        "wangfang",
        {"assigned_to": assignee["id"], "event_type": "设备安全", "severity": "P1"},
    )
    return {"event_id": event_id, "event_type": "设备安全", "severity": "P1"}


def _create_historical_event(
    api: FormalAPI, index: int, assignee: dict[str, Any], reporter: dict[str, Any]
) -> dict[str, str]:
    template = HISTORICAL_TEMPLATES[index % len(HISTORICAL_TEMPLATES)]
    sequence = index + 1
    raw_text = f"{template.place}：{template.summary} 当前为第 {sequence:03d} 次复核记录，现场责任已明确。"
    response = api.post(
        "/api/v1/admin/events",
        "wangfang",
        {
            "raw_text": raw_text,
            "event_type": template.event_type,
            "severity": template.severity,
            "from_user": reporter["id"],
        },
    )
    event_id = str(response["event_id"])
    api.patch(
        f"/api/v1/admin/events/{event_id}",
        "wangfang",
        {
            "assigned_to": assignee["id"],
            "event_type": template.event_type,
            "severity": template.severity,
        },
    )
    return {
        "event_id": event_id,
        "event_type": template.event_type,
        "severity": template.severity,
    }


def _advance_task(
    api: FormalAPI, task: CreatedTask, mode: str, index: int
) -> CreatedTask:
    if mode == "RUNNING":
        response = api.post(f"/api/v1/admin/tasks/{task.task_id}/start", "wangfang")
        task.status = str(response["task"]["status"])
    elif mode == "DONE":
        response = api.post(f"/api/v1/admin/tasks/{task.task_id}/start", "wangfang")
        task.status = str(response["task"]["status"])
        response = api.post(
            f"/api/v1/admin/tasks/{task.task_id}/complete",
            "wangfang",
            {
                "result": {
                    "summary": f"第 {index + 1} 次复核已完成，结果已归档",
                    "outcome": "HANDLED",
                }
            },
        )
        task.status = str(response["task"]["status"])
    elif mode == "FAILED":
        response = api.post(f"/api/v1/admin/tasks/{task.task_id}/start", "wangfang")
        task.status = str(response["task"]["status"])
        response = api.post(
            f"/api/v1/admin/tasks/{task.task_id}/fail",
            "wangfang",
            {"error": "现场数据缺少一项复核记录，需要补充后重新提交"},
        )
        task.status = str(response["task"]["status"])
    return task


def _create_tasks(
    api: FormalAPI,
    event: dict[str, str],
    users: dict[str, dict[str, Any]],
    index: int,
    tasks_per_event: int,
) -> list[CreatedTask]:
    users_in_rotation = [
        users["wangfang"],
        users["chenyu"],
        users["liming"],
        users["knowledge-owner"],
    ]
    agents = {
        "wangfang": "commander",
        "chenyu": "field-technician",
        "liming": "field-operator",
        "knowledge-owner": "TodoWrite",
    }
    status_modes = ("PENDING", "RUNNING", "DONE", "FAILED")
    created: list[CreatedTask] = []
    first_task_id: str | None = None
    for slot in range(tasks_per_event):
        assignee = users_in_rotation[(index + slot) % len(users_in_rotation)]
        dependencies = (
            [first_task_id] if slot == 1 and first_task_id and index % 5 == 0 else []
        )
        response = api.post(
            "/api/v1/admin/tasks",
            "wangfang",
            {
                "session_id": f"scenic-session-{assignee['username']}",
                "event_id": event["event_id"],
                "description": f"{event['event_type']}处置任务：{HISTORICAL_TEMPLATES[index % len(HISTORICAL_TEMPLATES)].task_focus}",
                "dependencies": dependencies,
                "assigned_user_id": assignee["id"],
                "assigned_agent": agents[assignee["username"]],
                "max_attempts": 3,
            },
        )
        task_payload = response["task"]
        task = CreatedTask(
            task_id=str(task_payload["id"]),
            event_id=event["event_id"],
            session_id=str(task_payload["session_id"]),
            assigned_user_id=str(task_payload["assigned_user_id"]),
            status=str(task_payload["status"]),
        )
        first_task_id = first_task_id or task.task_id
        if dependencies:
            # 依赖未满足：任务留在服务端真实状态，只标记本地跳过推进，
            # 不把服务器没有的 BLOCKED 状态写进证据。
            task.dependency_blocked = True
        else:
            mode = status_modes[(index + slot) % len(status_modes)]
            task = _advance_task(api, task, mode, index)
        created.append(task)
    return created


def _create_approvals(
    api: FormalAPI,
    candidates: list[CreatedTask],
    count: int,
    interval: float,
) -> list[dict[str, str]]:
    created: list[dict[str, str]] = []
    for index in range(min(count, len(candidates))):
        if index:
            time.sleep(interval)
        task = candidates[index]
        tool_name = "send_in_app_alert" if index % 2 == 0 else "record_manager_decision"
        action_code = (
            "SEND_CRITICAL_DISPATCH_ALERT"
            if tool_name == "send_in_app_alert"
            else (
                "SUSPEND_PASSENGER_VEHICLE"
                if index % 4 == 1
                else "ACTIVATE_BACKUP_VEHICLE"
            )
        )
        body = {
            "action_code": action_code,
            "tool_name": tool_name,
            "session_id": task.session_id,
            "event_id": task.event_id,
            "task_id": task.task_id,
            "message": "请核对现场证据并完成高风险处置决策"
            if tool_name == "record_manager_decision"
            else "请关注当前事件并同步调度处置进展",
            "priority": "critical" if tool_name == "send_in_app_alert" else "high",
        }
        for attempt in range(3):
            try:
                response = api.post(
                    "/api/v1/admin/action-requests",
                    "wangfang",
                    body,
                    key=_id(f"bulk-approval-{index}-{attempt}"),
                )
                approval_id = str(response["approval_id"])
                created.append(
                    {
                        "approval_id": approval_id,
                        "tool_name": tool_name,
                        "task_id": task.task_id,
                    }
                )
                break
            except EnrichmentError as exc:
                if "ACTION_COOLDOWN" not in str(exc) or attempt == 2:
                    raise
                time.sleep(62)
    return created


def _review_approvals(
    api: FormalAPI, approvals: list[dict[str, str]]
) -> dict[str, int]:
    reviewed = {"approved": 0, "rejected": 0, "pending": 0}
    for index, approval in enumerate(approvals):
        if index % 5 == 3:
            api.post(
                f"/api/v1/admin/approvals/{approval['approval_id']}/reject",
                "wangfang",
                {"comment": "证据仍不完整，补齐现场记录后重新提交"},
            )
            reviewed["rejected"] += 1
        elif index % 5 == 4:
            reviewed["pending"] += 1
        else:
            api.post(
                f"/api/v1/admin/approvals/{approval['approval_id']}/approve",
                "wangfang",
                {"comment": "证据和处置边界已核对，同意执行"},
            )
            reviewed["approved"] += 1
    return reviewed


def _vary_push_adoption(api: FormalAPI, before_ids: set[str]) -> int:
    rows = _items(api.get("/api/v1/admin/push_logs?limit=500", "wangfang"), "push_logs")
    changed = 0
    statuses = ("adopted", "adopted", "rejected", "pending")
    for index, row in enumerate(rows):
        push_id = str(row.get("push_id") or "")
        if not push_id or push_id in before_ids:
            continue
        status = statuses[index % len(statuses)]
        api.patch(
            f"/api/v1/admin/push_logs/{push_id}/adoption",
            "wangfang",
            {
                "status": status,
                "notes": "批量演示数据复核" if status != "pending" else None,
            },
        )
        changed += 1
    return changed


def _distribution(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "未填写")
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items(), key=lambda item: (-item[1], item[0])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SCENIC_E2E_BASE_URL", "http://127.0.0.1:8090"),
    )
    parser.add_argument("--simulated-events", type=int, default=40)
    parser.add_argument("--historical-events", type=int, default=100)
    parser.add_argument("--tasks-per-event", type=int, default=3)
    parser.add_argument("--approval-count", type=int, default=20)
    parser.add_argument("--approval-interval", type=float, default=31.0)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    password = (
        os.environ.get("SCENIC_E2E_PASSWORD")
        or os.environ.get("SCENIC_ACCOUNT_PASSWORD")
        or ""
    ).strip()
    if not password:
        raise SystemExit(
            "Set SCENIC_E2E_PASSWORD or SCENIC_ACCOUNT_PASSWORD before running"
        )

    api = FormalAPI(args.base_url, password)
    started_at = datetime.now(timezone.utc)
    evidence: dict[str, Any] = {
        "generated_at": started_at.isoformat(),
        "base_url": args.base_url,
        "simulated_events_requested": args.simulated_events,
        "historical_events_requested": args.historical_events,
        "tasks_per_event": args.tasks_per_event,
        "approval_count_requested": args.approval_count,
        "formal_api_only": True,
        "direct_database_writes": False,
    }
    try:
        for username in (
            "simulation-ops",
            "wangfang",
            "knowledge-owner",
            "chenyu",
            "liming",
        ):
            api.login(username)
        users = {
            item["username"]: item
            for item in _items(
                api.get("/api/v1/admin/assignees", "wangfang"), "assignees"
            )
            if item.get("username")
            in {"wangfang", "knowledge-owner", "chenyu", "liming"}
        }
        for username in ("wangfang", "knowledge-owner", "chenyu", "liming"):
            if username not in users:
                raise EnrichmentError(f"missing required user: {username}")

        evidence["counts_before"] = _counts(api, "wangfang")
        before_push_ids = {
            str(item.get("push_id") or "")
            for item in _items(
                api.get("/api/v1/admin/push_logs?limit=500", "wangfang"), "push_logs"
            )
        }

        created_events: list[dict[str, str]] = []
        created_tasks: list[CreatedTask] = []
        for index in range(args.simulated_events):
            assignee = [
                users["wangfang"],
                users["chenyu"],
                users["liming"],
                users["knowledge-owner"],
            ][index % 4]
            event = _create_simulated_event(api, index, assignee)
            created_events.append(event)
            created_tasks.extend(
                _create_tasks(api, event, users, index, args.tasks_per_event)
            )
            if (index + 1) % 10 == 0:
                print(
                    f"simulated events: {index + 1}/{args.simulated_events}", flush=True
                )

        for index in range(args.historical_events):
            assignee = [
                users["knowledge-owner"],
                users["liming"],
                users["chenyu"],
                users["wangfang"],
            ][index % 4]
            reporter = [
                users["liming"],
                users["chenyu"],
                users["knowledge-owner"],
                users["wangfang"],
            ][index % 4]
            event = _create_historical_event(api, index, assignee, reporter)
            created_events.append(event)
            created_tasks.extend(
                _create_tasks(
                    api,
                    event,
                    users,
                    index + args.simulated_events,
                    args.tasks_per_event,
                )
            )
            if (index + 1) % 10 == 0:
                print(
                    f"historical events: {index + 1}/{args.historical_events}",
                    flush=True,
                )

        candidates = [
            task
            for task in created_tasks
            if task.status == "PENDING" and not task.dependency_blocked
        ]
        approval_rows = _create_approvals(
            api, candidates, args.approval_count, args.approval_interval
        )
        evidence["review_results"] = _review_approvals(api, approval_rows)
        time.sleep(2)
        evidence["push_adoption_updated"] = _vary_push_adoption(api, before_push_ids)

        evidence["created"] = {
            "events": len(created_events),
            "tasks": len(created_tasks),
            "approvals": len(approval_rows),
            "approval_reviews": evidence["review_results"],
        }
        evidence["counts_after"] = _counts(api, "wangfang")
        event_rows = _items(
            api.get("/api/v1/admin/events?limit=500", "wangfang"), "events"
        )
        task_rows = _items(
            api.get("/api/v1/admin/tasks?limit=500", "wangfang"), "tasks"
        )
        approval_list = _items(
            api.get("/api/v1/admin/approvals?status=ALL", "wangfang"), "approvals"
        )
        push_rows = _items(
            api.get("/api/v1/admin/push_logs?limit=500", "wangfang"), "push_logs"
        )
        evidence["distributions"] = {
            "event_type": _distribution(event_rows, "event_type"),
            "event_severity": _distribution(event_rows, "severity"),
            "event_status": _distribution(event_rows, "status"),
            "event_assignee": _distribution(event_rows, "assigned_to"),
            "task_status": _distribution(task_rows, "status"),
            "task_agent": _distribution(task_rows, "assigned_agent"),
            "task_assignee": _distribution(task_rows, "assigned_user_id"),
            "approval_status": _distribution(approval_list, "status"),
            "approval_tool": _distribution(approval_list, "tool_name"),
            "push_channel": _distribution(push_rows, "channel"),
            "push_delivery": _distribution(push_rows, "delivery_status"),
            "push_adoption": _distribution(push_rows, "adoption_status"),
        }
        evidence["ok"] = True
    except Exception as exc:  # noqa: BLE001 - record any failed formal step
        evidence["ok"] = False
        evidence["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        api.close()
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        evidence["duration_seconds"] = round(
            (datetime.now(timezone.utc) - started_at).total_seconds(), 2
        )
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "ok": evidence.get("ok"),
                    "counts_before": evidence.get("counts_before"),
                    "counts_after": evidence.get("counts_after"),
                    "created": evidence.get("created"),
                    "error": evidence.get("error"),
                    "evidence": str(args.evidence),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if evidence.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
