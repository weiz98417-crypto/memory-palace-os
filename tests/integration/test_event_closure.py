import json
import time

import httpx
import pytest

from tests.integration.test_mvp_business_apis import build_app, create_user, login


DETAILED_RESOLUTION = (
    "已更换防松螺栓并校正右后轮防尘护板，完成空载低速三轮试车，"
    "确认无异响、无制动跑偏且温度正常；12 号车今晚继续停运观察，"
    "7 号备用车已完成交接并投入运行。"
)


async def _create_event(client, headers, *, marker: str, from_user: str) -> str:
    response = await client.post(
        "/admin/events",
        headers=headers,
        json={
            "raw_text": f"{marker}：观光车右后轮出现间歇性金属摩擦声。",
            "event_type": "车辆设备故障",
            "severity": "P2",
            "from_user": from_user,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["event_id"]


async def _seed_task(
    database,
    *,
    marker: str,
    event_id: str,
    venue_id: str = "venue-alpha",
    status: str = "DONE",
) -> tuple[str, str]:
    now = time.time()
    task_id = f"task-close-{marker}"
    session_id = f"session-close-{marker}"
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, stage, created_at, updated_at
        ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (session_id, f"user-{marker}", venue_id, now, now),
    )
    await database.execute(
        """
        INSERT INTO tasks (
            id, business_id, venue_id, session_id, event_id, description,
            status, dependencies, result, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?)
        """,
        (
            task_id,
            f"RW-CLOSE-{marker.upper()}",
            venue_id,
            session_id,
            event_id,
            "启用备用车并通知调度",
            status,
            json.dumps(
                {"summary": "备用车已交接并通知调度"},
                ensure_ascii=False,
            )
            if status == "DONE"
            else None,
            now,
            now,
            now if status == "DONE" else None,
        ),
    )
    return task_id, session_id


async def _seed_approval(
    database,
    *,
    marker: str,
    event_id: str,
    task_id: str,
    session_id: str,
    status: str,
    execution_status: str,
    venue_id: str = "venue-alpha",
    supersedes_approval_id: str | None = None,
    execution_error: str | None = None,
) -> str:
    approval_id = f"approval-close-{marker}"
    await database.execute(
        """
        INSERT INTO approval_requests (
            approval_id, business_id, venue_id, tool_name, args, session_id,
            event_id, task_id, user_id, requested_at, requested_by,
            supersedes_approval_id, status, execution_status,
            execution_result, execution_error
        ) VALUES (?, ?, ?, 'send_in_app_alert', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            approval_id,
            f"SP-CLOSE-{marker.upper()}",
            venue_id,
            json.dumps(
                {"message": "启用备用车并通知调度", "level": "warning"},
                ensure_ascii=False,
            ),
            session_id,
            event_id,
            task_id,
            f"user-{marker}",
            time.time(),
            f"user-{marker}",
            supersedes_approval_id,
            status,
            execution_status,
            json.dumps({"status": "executed"}, ensure_ascii=False)
            if execution_status == "SUCCEEDED"
            else None,
            execution_error,
        ),
    )
    return approval_id


async def _event_detail(client, headers, event_id: str) -> dict:
    response = await client.get(f"/admin/events/{event_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _assert_close_denied(
    client,
    headers,
    *,
    event_id: str,
    blocker_code: str,
) -> dict:
    response = await client.post(
        f"/admin/events/{event_id}/close",
        headers=headers,
        json={"resolution": DETAILED_RESOLUTION},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "EVENT_CLOSE_BLOCKED"
    conditions = detail["closure_conditions"]
    assert conditions["ready"] is False
    assert conditions["blocker_count"] >= 1
    assert conditions["blocker_counts"][blocker_code] >= 1
    assert blocker_code in {blocker["code"] for blocker in conditions["blockers"]}

    event = await _event_detail(client, headers, event_id)
    assert event["status"] == "OPEN"
    assert event["resolution"] is None
    assert event["closed_at"] is None
    assert event["dossier"]["summary"]["status"] == "OPEN"
    assert event["dossier"]["summary"]["close_ready"] is False

    audits = await client.get(
        "/admin/audit-logs",
        headers=headers,
        params={"action": "EVENT_CLOSE_DENIED"},
    )
    assert audits.status_code == 200, audits.text
    matching_audits = [
        row
        for row in audits.json()["audit_logs"]
        if row["resource_type"] == "event" and row["resource_id"] == event_id
    ]
    assert len(matching_audits) == 1
    assert matching_audits[0]["outcome"] == "DENIED"
    return conditions


@pytest.mark.asyncio
async def test_event_close_denies_unfinished_task_and_keeps_event_open(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(
                client,
                "mvp-admin",
                "Mvp-Admin-Password-2026",
            )
            event_id = await _create_event(
                client,
                admin_headers,
                marker="未完成任务门禁",
                from_user="现场员工-任务门禁",
            )
            task_id, _ = await _seed_task(
                database,
                marker="unfinished",
                event_id=event_id,
                status="PENDING",
            )

            conditions = await _assert_close_denied(
                client,
                admin_headers,
                event_id=event_id,
                blocker_code="UNFINISHED_TASK",
            )

            unfinished = next(
                blocker
                for blocker in conditions["blockers"]
                if blocker["code"] == "UNFINISHED_TASK"
            )
            assert unfinished["resource_id"] == task_id
            assert unfinished["status"] == "PENDING"
            assert "启用备用车并通知调度" in unfinished["message"]
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_close_denies_pending_approval(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(
                client,
                "mvp-admin",
                "Mvp-Admin-Password-2026",
            )
            event_id = await _create_event(
                client,
                admin_headers,
                marker="待审批门禁",
                from_user="现场员工-待审批",
            )
            task_id, session_id = await _seed_task(
                database,
                marker="pending-approval",
                event_id=event_id,
            )
            approval_id = await _seed_approval(
                database,
                marker="pending",
                event_id=event_id,
                task_id=task_id,
                session_id=session_id,
                status="PENDING",
                execution_status="NOT_STARTED",
            )

            conditions = await _assert_close_denied(
                client,
                admin_headers,
                event_id=event_id,
                blocker_code="PENDING_APPROVAL",
            )

            pending = next(
                blocker
                for blocker in conditions["blockers"]
                if blocker["code"] == "PENDING_APPROVAL"
            )
            assert pending["resource_id"] == approval_id
            assert pending["status"] == "PENDING"
            assert pending["execution_status"] == "NOT_STARTED"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_close_denies_approved_action_with_failed_execution(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(
                client,
                "mvp-admin",
                "Mvp-Admin-Password-2026",
            )
            event_id = await _create_event(
                client,
                admin_headers,
                marker="动作失败门禁",
                from_user="现场员工-动作失败",
            )
            task_id, session_id = await _seed_task(
                database,
                marker="failed-action",
                event_id=event_id,
            )
            approval_id = await _seed_approval(
                database,
                marker="failed",
                event_id=event_id,
                task_id=task_id,
                session_id=session_id,
                status="APPROVED",
                execution_status="FAILED",
                execution_error="企微模拟器出站队列写入失败",
            )

            conditions = await _assert_close_denied(
                client,
                admin_headers,
                event_id=event_id,
                blocker_code="ACTION_EXECUTION_FAILED",
            )

            failed = next(
                blocker
                for blocker in conditions["blockers"]
                if blocker["code"] == "ACTION_EXECUTION_FAILED"
            )
            assert failed["resource_id"] == approval_id
            assert failed["status"] == "APPROVED"
            assert failed["execution_status"] == "FAILED"
            assert failed["execution_error"] == "企微模拟器出站队列写入失败"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_close_requires_rejected_approval_to_be_superseded(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(
                client,
                "mvp-admin",
                "Mvp-Admin-Password-2026",
            )
            event_id = await _create_event(
                client,
                admin_headers,
                marker="拒绝后重提门禁",
                from_user="现场员工-拒绝重提",
            )
            task_id, session_id = await _seed_task(
                database,
                marker="rejected-action",
                event_id=event_id,
            )
            rejected_id = await _seed_approval(
                database,
                marker="rejected",
                event_id=event_id,
                task_id=task_id,
                session_id=session_id,
                status="REJECTED",
                execution_status="NOT_STARTED",
            )

            denied_conditions = await _assert_close_denied(
                client,
                admin_headers,
                event_id=event_id,
                blocker_code="UNRESOLVED_REJECTION",
            )
            rejected_blocker = next(
                blocker
                for blocker in denied_conditions["blockers"]
                if blocker["code"] == "UNRESOLVED_REJECTION"
            )
            assert rejected_blocker["resource_id"] == rejected_id

            await _seed_approval(
                database,
                marker="resubmitted",
                event_id=event_id,
                task_id=task_id,
                session_id=session_id,
                status="APPROVED",
                execution_status="SUCCEEDED",
                supersedes_approval_id=rejected_id,
            )
            ready_event = await _event_detail(client, admin_headers, event_id)
            ready_conditions = ready_event["dossier"]["summary"][
                "closure_conditions"
            ]
            assert ready_conditions["ready"] is True
            assert ready_conditions["blocker_count"] == 0
            assert ready_conditions["blockers"] == []

            closed = await client.post(
                f"/admin/events/{event_id}/close",
                headers=admin_headers,
                json={"resolution": DETAILED_RESOLUTION},
            )
            assert closed.status_code == 200, closed.text
            assert closed.json()["closure_conditions"]["ready"] is True
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_close_persists_audit_activity_and_makes_event_immutable(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(
                client,
                "mvp-admin",
                "Mvp-Admin-Password-2026",
            )
            event_id = await _create_event(
                client,
                admin_headers,
                marker="成功闭环",
                from_user="现场员工-成功闭环",
            )
            task_id, session_id = await _seed_task(
                database,
                marker="ready",
                event_id=event_id,
            )
            await _seed_approval(
                database,
                marker="succeeded",
                event_id=event_id,
                task_id=task_id,
                session_id=session_id,
                status="APPROVED",
                execution_status="SUCCEEDED",
            )

            closed = await client.post(
                f"/admin/events/{event_id}/close",
                headers=admin_headers,
                json={"resolution": DETAILED_RESOLUTION},
            )
            assert closed.status_code == 200, closed.text
            closed_payload = closed.json()
            assert closed_payload["closed"] is True
            assert closed_payload["event_id"] == event_id
            assert closed_payload["closure_conditions"]["ready"] is True
            assert closed_payload["closure_conditions"]["blocker_count"] == 0

            detail = await _event_detail(client, admin_headers, event_id)
            assert detail["status"] == "CLOSED"
            assert detail["resolution"] == DETAILED_RESOLUTION
            assert detail["closed_at"] is not None
            assert detail["dossier"]["summary"]["status"] == "CLOSED"
            assert detail["dossier"]["summary"]["resolution"] == DETAILED_RESOLUTION
            assert detail["dossier"]["summary"]["close_ready"] is False
            closed_activities = [
                activity
                for activity in detail["dossier"]["timeline"]
                if activity["technical"]["activity_type"] == "EVENT_CLOSED"
            ]
            assert len(closed_activities) == 1
            assert closed_activities[0]["summary"] == DETAILED_RESOLUTION

            audits = await client.get(
                "/admin/audit-logs",
                headers=admin_headers,
                params={"action": "EVENT_CLOSED"},
            )
            assert audits.status_code == 200, audits.text
            matching_audits = [
                row
                for row in audits.json()["audit_logs"]
                if row["resource_type"] == "event" and row["resource_id"] == event_id
            ]
            assert len(matching_audits) == 1
            assert matching_audits[0]["outcome"] == "SUCCEEDED"

            modified = await client.patch(
                f"/admin/events/{event_id}",
                headers=admin_headers,
                json={"severity": "P0"},
            )
            assert modified.status_code == 409, modified.text
            assert modified.json()["detail"]["code"] == "EVENT_ALREADY_CLOSED"
            closed_again = await client.post(
                f"/admin/events/{event_id}/close",
                headers=admin_headers,
                json={"resolution": "试图覆盖原闭环结论。"},
            )
            assert closed_again.status_code == 409, closed_again.text
            assert closed_again.json()["detail"]["code"] == "EVENT_ALREADY_CLOSED"

            unchanged = await _event_detail(client, admin_headers, event_id)
            assert unchanged["severity"] == "P2"
            assert unchanged["resolution"] == DETAILED_RESOLUTION
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_event_close_is_strictly_tenant_isolated(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(
                client,
                "mvp-admin",
                "Mvp-Admin-Password-2026",
            )
            venue = await client.post(
                "/admin/venues",
                headers=admin_headers,
                json={"id": "venue-beta", "name": "南麓游客中心"},
            )
            assert venue.status_code == 201, venue.text
            beta_manager = await create_user(
                client,
                admin_headers,
                username="closure-beta-manager",
                role="manager",
                venue_id="venue-beta",
            )
            beta_headers = await login(
                client,
                beta_manager["username"],
                "Strong-Password-2026",
            )
            event_id = await _create_event(
                client,
                admin_headers,
                marker="租户隔离闭环",
                from_user="现场员工-租户隔离",
            )

            foreign_task_id, foreign_session_id = await _seed_task(
                database,
                marker="foreign-blocker",
                event_id=event_id,
                venue_id="venue-beta",
                status="PENDING",
            )
            await _seed_approval(
                database,
                marker="foreign-blocker",
                event_id=event_id,
                task_id=foreign_task_id,
                session_id=foreign_session_id,
                venue_id="venue-beta",
                status="PENDING",
                execution_status="NOT_STARTED",
            )

            closed = await client.post(
                f"/admin/events/{event_id}/close",
                headers=admin_headers,
                json={"resolution": DETAILED_RESOLUTION},
            )
            assert closed.status_code == 200, closed.text
            assert closed.json()["closure_conditions"]["task_count"] == 0
            assert closed.json()["closure_conditions"]["approval_count"] == 0
            assert closed.json()["closure_conditions"]["ready"] is True

            foreign_detail = await client.get(
                f"/admin/events/{event_id}",
                headers=beta_headers,
            )
            assert foreign_detail.status_code == 404, foreign_detail.text
            assert foreign_detail.json()["detail"]["code"] == "EVENT_NOT_FOUND"
            foreign_close = await client.post(
                f"/admin/events/{event_id}/close",
                headers=beta_headers,
                json={"resolution": DETAILED_RESOLUTION},
            )
            assert foreign_close.status_code == 404, foreign_close.text
            assert foreign_close.json()["detail"]["code"] == "EVENT_NOT_FOUND"

            alpha_audits = await client.get(
                "/admin/audit-logs",
                headers=admin_headers,
                params={"action": "EVENT_CLOSED"},
            )
            beta_audits = await client.get(
                "/admin/audit-logs",
                headers=beta_headers,
                params={"action": "EVENT_CLOSED"},
            )
            assert {
                row["resource_id"] for row in alpha_audits.json()["audit_logs"]
            } == {event_id}
            assert beta_audits.json()["audit_logs"] == []
    finally:
        await database.close()
