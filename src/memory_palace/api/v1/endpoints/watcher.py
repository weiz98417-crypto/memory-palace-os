"""Formal Watcher policy, run, and finding endpoints."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Literal, Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth, require_roles
from ...errors import api_error
from ....core.watcher_runtime import (
    WatcherRunFailed,
    run_event_watcher_check,
    run_watcher_policy,
)


router = APIRouter(dependencies=[Depends(require_auth)])


class WatcherPolicyCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str = Field("", max_length=1000)
    schedule_cron: str = Field("0 10 * * *", min_length=9, max_length=80)
    enabled: bool = True
    check_types: list[Literal["SLA", "TASK", "SOP"]] = Field(default_factory=lambda: ["SLA", "TASK", "SOP"])
    config: dict[str, Any] = Field(default_factory=lambda: {"max_targets": 200})


class WatcherPolicyUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)
    schedule_cron: Optional[str] = Field(None, min_length=9, max_length=80)
    enabled: Optional[bool] = None
    check_types: Optional[list[Literal["SLA", "TASK", "SOP"]]] = None
    config: Optional[dict[str, Any]] = None


class FindingUpdateRequest(BaseModel):
    assigned_to: Optional[str] = Field(None, max_length=64)
    status: Optional[Literal["OPEN", "IN_PROGRESS"]] = None


class FindingCloseRequest(BaseModel):
    resolution: str = Field(..., min_length=3, max_length=4000)


def _decode_policy(row: dict[str, Any]) -> dict[str, Any]:
    for source, target, default in (
        ("check_types_json", "check_types", []),
        ("config_json", "config", {}),
    ):
        try:
            row[target] = json.loads(row.pop(source, None) or json.dumps(default))
        except (TypeError, json.JSONDecodeError):
            row[target] = default
    row["enabled"] = bool(row.get("enabled"))
    return row


def _validate_cron(request: Request, cron: str) -> None:
    try:
        CronTrigger.from_crontab(cron, timezone="Asia/Shanghai")
    except ValueError as exc:
        raise api_error(request, 422, "WATCHER_CRON_INVALID", "巡检计划必须是标准五段 Cron 表达式。", "修正执行计划后重试。") from exc


async def _reload_scheduler(request: Request) -> None:
    scheduler = getattr(request.app.state, "scheduler", None)
    reload_jobs = getattr(scheduler, "reload_jobs", None)
    if callable(reload_jobs):
        await reload_jobs()


@router.post("/events/{event_id}/watcher-check")
async def check_event_before_closure(
    event_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    try:
        result = await run_event_watcher_check(
            db,
            event_id=event_id,
            venue_id=principal["venue_id"],
            actor_id=principal["user_id"],
        )
    except LookupError as exc:
        raise api_error(
            request,
            404,
            "EVENT_NOT_FOUND",
            "事件不存在。",
            "刷新事件列表后重试。",
        ) from exc
    except WatcherRunFailed as exc:
        request.state.trace_id = exc.trace_id
        await write_audit(
            db,
            principal=principal,
            action="EVENT_WATCHER_CHECK",
            resource_type="event",
            resource_id=event_id,
            outcome="FAILED",
            trace_id=exc.trace_id,
            metadata={
                "run_id": exc.run_id,
                "model": "deepseek-flash",
                "error_type": type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
            },
        )
        raise api_error(
            request,
            502,
            "WATCHER_EVENT_CHECK_FAILED",
            "闭环检查运行失败，事件尚未通过检查。",
            "查看失败运行和模型健康状态后重试。",
            retryable=True,
            details={"run_id": exc.run_id, "run_status": "FAILED"},
        ) from exc

    await write_audit(
        db,
        principal=principal,
        action="EVENT_WATCHER_CHECK",
        resource_type="event",
        resource_id=event_id,
        outcome="SUCCEEDED",
        trace_id=result["trace_id"],
        metadata={
            "run_id": result["run"]["id"],
            "finding_count": len(result["findings"]),
            "ready_to_close": result["ready_to_close"],
            "model": result["model"],
        },
    )
    return result


@router.get("/watcher/policies")
async def list_watcher_policies(
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    rows = await db.fetch_all(
        "SELECT * FROM watcher_policies WHERE venue_id = ? ORDER BY updated_at DESC",
        (principal["venue_id"],),
    )
    return {"policies": [_decode_policy(row) for row in rows]}


@router.post("/watcher/policies", status_code=status.HTTP_201_CREATED)
async def create_watcher_policy(
    body: WatcherPolicyCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    _validate_cron(request, body.schedule_cron)
    policy_id = uuid.uuid4().hex
    now = time.time()
    await db.execute(
        """
        INSERT INTO watcher_policies (
            id, venue_id, name, description, schedule_cron, enabled,
            check_types_json, config_json, version, created_by,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            policy_id,
            principal["venue_id"],
            body.name.strip(),
            body.description.strip(),
            body.schedule_cron,
            body.enabled,
            json.dumps(body.check_types, ensure_ascii=False),
            json.dumps(body.config, ensure_ascii=False),
            principal["user_id"],
            now,
            now,
        ),
    )
    await _reload_scheduler(request)
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="WATCHER_POLICY_CREATED",
        resource_type="watcher_policy",
        resource_id=policy_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"schedule_cron": body.schedule_cron, "enabled": body.enabled},
    )
    row = await db.fetch_one("SELECT * FROM watcher_policies WHERE id = ?", (policy_id,))
    return {"policy": _decode_policy(row), "trace_id": trace_id}


@router.put("/watcher/policies/{policy_id}")
async def update_watcher_policy(
    policy_id: str,
    body: WatcherPolicyUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one(
        "SELECT * FROM watcher_policies WHERE id = ? AND venue_id = ?",
        (policy_id, principal["venue_id"]),
    )
    if not current:
        raise api_error(request, 404, "WATCHER_POLICY_NOT_FOUND", "巡检策略不存在。", "刷新策略列表后重试。")
    updates = body.model_dump(exclude_none=True)
    if "schedule_cron" in updates:
        _validate_cron(request, updates["schedule_cron"])
    if "check_types" in updates:
        updates["check_types_json"] = json.dumps(updates.pop("check_types"), ensure_ascii=False)
    if "config" in updates:
        updates["config_json"] = json.dumps(updates.pop("config"), ensure_ascii=False)
    if updates:
        set_sql = ", ".join(f"{column} = ?" for column in updates)
        await db.execute(
            f"UPDATE watcher_policies SET {set_sql}, version = version + 1, updated_at = ? WHERE id = ? AND venue_id = ?",
            (*updates.values(), time.time(), policy_id, principal["venue_id"]),
        )
        await _reload_scheduler(request)
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="WATCHER_POLICY_UPDATED",
        resource_type="watcher_policy",
        resource_id=policy_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"changed_fields": sorted(updates)},
    )
    row = await db.fetch_one("SELECT * FROM watcher_policies WHERE id = ?", (policy_id,))
    return {"policy": _decode_policy(row), "trace_id": trace_id}


@router.post("/watcher/policies/{policy_id}/run")
async def run_policy_now(
    policy_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    policy = await db.fetch_one(
        "SELECT id, enabled FROM watcher_policies WHERE id = ? AND venue_id = ?",
        (policy_id, principal["venue_id"]),
    )
    if not policy:
        raise api_error(request, 404, "WATCHER_POLICY_NOT_FOUND", "巡检策略不存在。", "刷新策略列表后重试。")
    if not bool(policy["enabled"]):
        raise api_error(request, 409, "WATCHER_POLICY_DISABLED", "停用的巡检策略不能运行。", "先启用策略。")
    try:
        result = await run_watcher_policy(
            db,
            policy_id=policy_id,
            venue_id=principal["venue_id"],
            trigger_source="MANUAL",
        )
    except Exception as exc:
        trace_id = request_trace_id(request)
        await write_audit(
            db,
            principal=principal,
            action="WATCHER_RUN",
            resource_type="watcher_policy",
            resource_id=policy_id,
            outcome="FAILED",
            trace_id=trace_id,
            metadata={"error_type": type(exc).__name__},
        )
        raise api_error(request, 502, "WATCHER_RUN_FAILED", "巡检运行失败。", "查看运行记录和模型健康后重试。", retryable=True) from exc
    await write_audit(
        db,
        principal=principal,
        action="WATCHER_RUN",
        resource_type="watcher_run",
        resource_id=result["run_id"],
        outcome="SUCCEEDED",
        trace_id=result["trace_id"],
        metadata={"policy_id": policy_id, "finding_count": result["finding_count"]},
    )
    return result


@router.get("/watcher/runs")
async def list_watcher_runs(
    run_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM watcher_runs WHERE venue_id = ?"
    params: list[Any] = [principal["venue_id"]]
    if run_status:
        sql += " AND status = ?"
        params.append(run_status.upper())
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    rows = await db.fetch_all(sql, tuple(params))
    for row in rows:
        try:
            row["result"] = json.loads(row.pop("result_json", "{}") or "{}")
        except (TypeError, json.JSONDecodeError):
            row["result"] = {}
    return {"runs": rows}


@router.get("/watcher/findings")
async def list_watcher_findings(
    finding_status: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM watcher_findings WHERE venue_id = ?"
    params: list[Any] = [principal["venue_id"]]
    if finding_status:
        sql += " AND status = ?"
        params.append(finding_status.upper())
    if severity:
        sql += " AND severity = ?"
        params.append(severity.upper())
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return {"findings": await db.fetch_all(sql, tuple(params))}


@router.patch("/watcher/findings/{finding_id}")
async def update_watcher_finding(
    finding_id: str,
    body: FindingUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one(
        "SELECT * FROM watcher_findings WHERE id = ? AND venue_id = ?",
        (finding_id, principal["venue_id"]),
    )
    if not current:
        raise api_error(request, 404, "WATCHER_FINDING_NOT_FOUND", "巡检发现不存在。", "刷新发现列表后重试。")
    if current["status"] == "CLOSED":
        raise api_error(request, 409, "WATCHER_FINDING_CLOSED", "已关闭的巡检发现不能修改。", "查看处理结果。")
    updates = body.model_dump(exclude_none=True)
    if "assigned_to" in updates and updates["assigned_to"]:
        if not await db.fetch_one(
            "SELECT id FROM users WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
            (updates["assigned_to"], principal["venue_id"]),
        ):
            raise api_error(request, 400, "WATCHER_ASSIGNEE_INVALID", "负责人不存在、跨场地或已停用。", "请选择当前场地的有效用户。")
    if updates:
        set_sql = ", ".join(f"{column} = ?" for column in updates)
        await db.execute(
            f"UPDATE watcher_findings SET {set_sql}, updated_at = ? WHERE id = ? AND venue_id = ?",
            (*updates.values(), time.time(), finding_id, principal["venue_id"]),
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="WATCHER_FINDING_UPDATED",
        resource_type="watcher_finding",
        resource_id=finding_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"changed_fields": sorted(updates)},
    )
    return {
        "finding": await db.fetch_one("SELECT * FROM watcher_findings WHERE id = ?", (finding_id,)),
        "trace_id": trace_id,
    }


@router.post("/watcher/findings/{finding_id}/close")
async def close_watcher_finding(
    finding_id: str,
    body: FindingCloseRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one(
        "SELECT id, status FROM watcher_findings WHERE id = ? AND venue_id = ?",
        (finding_id, principal["venue_id"]),
    )
    if not current:
        raise api_error(request, 404, "WATCHER_FINDING_NOT_FOUND", "巡检发现不存在。", "刷新发现列表后重试。")
    if current["status"] == "CLOSED":
        raise api_error(request, 409, "WATCHER_FINDING_CLOSED", "巡检发现已经关闭。", "查看处理结果。")
    now = time.time()
    await db.execute(
        """
        UPDATE watcher_findings
        SET status = 'CLOSED', resolution = ?, closed_at = ?, updated_at = ?
        WHERE id = ? AND venue_id = ?
        """,
        (body.resolution.strip(), now, now, finding_id, principal["venue_id"]),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="WATCHER_FINDING_CLOSED",
        resource_type="watcher_finding",
        resource_id=finding_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    return {"closed": True, "finding_id": finding_id, "trace_id": trace_id}
