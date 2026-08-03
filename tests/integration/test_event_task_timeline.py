import httpx
import pytest

from src.memory_palace.api.v1.endpoints.assistant import router as assistant_router
from tests.integration.test_mvp_business_apis import build_app, create_user, login


TASK_LIFECYCLE_ACTIVITY_TYPES = {
    "TASK_ASSIGNED",
    "TASK_STARTED",
    "TASK_COMPLETED",
    "TASK_BLOCKED",
    "TASK_UNBLOCKED",
}


def task_lifecycle_timeline(dossier):
    return [
        entry
        for entry in dossier["timeline"]
        if entry["technical"]["activity_type"] in TASK_LIFECYCLE_ACTIVITY_TYPES
    ]


@pytest.mark.asyncio
async def test_event_update_is_readable_in_event_dossier_timeline(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(
            client,
            "mvp-admin",
            "Mvp-Admin-Password-2026",
        )
        assignee = await create_user(
            client,
            admin_headers,
            username="timeline-event-assignee",
            role="operator",
        )
        created = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "游客中心扶梯运行异常，需要现场排查。",
                "event_type": "设施故障",
                "severity": "P2",
                "from_user": assignee["id"],
            },
        )
        assert created.status_code == 200, created.text
        event_id = created.json()["event_id"]

        updated = await client.patch(
            f"/admin/events/{event_id}",
            headers=admin_headers,
            json={"severity": "P1", "assigned_to": assignee["id"]},
        )
        detail = await client.get(
            f"/admin/events/{event_id}",
            headers=admin_headers,
        )

    assert updated.status_code == 200, updated.text
    assert detail.status_code == 200, detail.text
    entries = [
        entry
        for entry in detail.json()["dossier"]["timeline"]
        if entry["technical"]["activity_type"] == "EVENT_UPDATED"
    ]
    assert len(entries) == 1
    assert entries[0]["label"] == "事件信息已更新"
    assert entries[0]["summary"] == "事件分类、等级或负责人信息已更新。"
    assert entries[0]["actor_name"] == "交付管理员"
    await database.close()


@pytest.mark.asyncio
async def test_admin_task_lifecycle_is_ordered_and_readable_in_event_dossier(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(
            client,
            "mvp-admin",
            "Mvp-Admin-Password-2026",
        )
        assignee = await create_user(
            client,
            admin_headers,
            username="timeline-admin-assignee",
            role="operator",
        )
        principal = await client.get("/auth/me", headers=admin_headers)
        assert principal.status_code == 200, principal.text

        created_event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "东门闸机断续离线，需要完成现场复位和三轮通行验证。",
                "event_type": "设施故障",
                "severity": "P1",
                "from_user": principal.json()["id"],
            },
        )
        assert created_event.status_code == 200, created_event.text
        event_id = created_event.json()["event_id"]

        created_task = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "session-admin-task-timeline",
                "event_id": event_id,
                "description": "复位东门闸机并完成三轮游客通行验证",
            },
        )
        assert created_task.status_code == 201, created_task.text
        task = created_task.json()["task"]
        task_id = task["id"]
        task_business_id = task["business_id"]
        assert task_business_id.startswith("RW-")

        assigned = await client.patch(
            f"/admin/tasks/{task_id}/assignment",
            headers=admin_headers,
            json={"assigned_user_id": assignee["id"]},
        )
        started = await client.post(
            f"/admin/tasks/{task_id}/start",
            headers=admin_headers,
        )
        completed = await client.post(
            f"/admin/tasks/{task_id}/complete",
            headers=admin_headers,
            json={
                "result": {
                    "summary": "东门闸机已复位，连续三轮通行验证均正常。",
                    "verification_rounds": 3,
                }
            },
        )
        detail = await client.get(
            f"/admin/events/{event_id}",
            headers=admin_headers,
        )

    assert assigned.status_code == 200, assigned.text
    assert started.status_code == 200, started.text
    assert completed.status_code == 200, completed.text
    assert detail.status_code == 200, detail.text

    dossier = detail.json()["dossier"]
    lifecycle = task_lifecycle_timeline(dossier)
    assert [entry["technical"]["activity_type"] for entry in lifecycle] == [
        "TASK_ASSIGNED",
        "TASK_STARTED",
        "TASK_COMPLETED",
    ]
    assert [entry["label"] for entry in lifecycle] == [
        "任务负责人已更新",
        "任务已开始",
        "任务已完成",
    ]
    assert [entry["summary"] for entry in lifecycle] == [
        "任务负责人已更新。",
        "任务已开始执行。",
        "东门闸机已复位，连续三轮通行验证均正常。",
    ]
    assert {entry["actor_name"] for entry in lifecycle} == {"交付管理员"}
    assert {entry["business_id"] for entry in lifecycle} == {task_business_id}
    assert all(task_id not in entry["summary"] for entry in lifecycle)
    assert dossier["tasks"][0]["business_id"] == task_business_id
    assert dossier["tasks"][0]["result"]["fields"] == {
        "summary": "东门闸机已复位，连续三轮通行验证均正常。",
        "verification_rounds": 3,
    }
    await database.close()


@pytest.mark.asyncio
async def test_assistant_block_and_manager_unblock_persist_only_in_linked_event_dossier(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(
            client,
            "mvp-admin",
            "Mvp-Admin-Password-2026",
        )
        manager = await create_user(
            client,
            admin_headers,
            username="timeline-alpha-manager",
            role="manager",
        )
        employee = await create_user(
            client,
            admin_headers,
            username="timeline-alpha-employee",
            role="operator",
        )
        manager_headers = await login(
            client,
            manager["username"],
            "Strong-Password-2026",
        )
        employee_headers = await login(
            client,
            employee["username"],
            "Strong-Password-2026",
        )

        linked_event = await client.post(
            "/admin/events",
            headers=manager_headers,
            json={
                "raw_text": "北门护栏受损，需要设置警戒带并拍照确认。",
                "event_type": "设施损坏",
                "severity": "P2",
                "from_user": employee["id"],
            },
        )
        unrelated_event = await client.post(
            "/admin/events",
            headers=manager_headers,
            json={
                "raw_text": "西门广播音量偏低，等待例行巡检。",
                "event_type": "设施巡检",
                "severity": "P3",
                "from_user": manager["id"],
            },
        )
        assert linked_event.status_code == 200, linked_event.text
        assert unrelated_event.status_code == 200, unrelated_event.text
        linked_event_id = linked_event.json()["event_id"]
        unrelated_event_id = unrelated_event.json()["event_id"]

        created_task = await client.post(
            "/admin/tasks",
            headers=manager_headers,
            json={
                "session_id": "session-assistant-block-timeline",
                "event_id": linked_event_id,
                "description": "设置北门警戒带并上传受损护栏照片",
                "assigned_user_id": employee["id"],
            },
        )
        assert created_task.status_code == 201, created_task.text
        task = created_task.json()["task"]
        task_business_id = task["business_id"]

        started = await client.post(
            f"/api/v1/assistant/work/tasks/{task['id']}/start",
            headers=employee_headers,
        )
        blocked = await client.post(
            f"/api/v1/assistant/work/tasks/{task['id']}/block",
            headers=employee_headers,
            json={"reason": "现场警戒带库存不足，需要仓库补充后继续。"},
        )
        unblocked = await client.post(
            f"/admin/tasks/{task['id']}/unblock",
            headers=manager_headers,
        )

        first_detail = await client.get(
            f"/admin/events/{linked_event_id}",
            headers=manager_headers,
        )
        refreshed_detail = await client.get(
            f"/admin/events/{linked_event_id}",
            headers=manager_headers,
        )
        unrelated_detail = await client.get(
            f"/admin/events/{unrelated_event_id}",
            headers=manager_headers,
        )

        created_venue = await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-timeline-beta", "name": "南麓景区"},
        )
        assert created_venue.status_code == 201, created_venue.text
        beta_manager = await create_user(
            client,
            admin_headers,
            username="timeline-beta-manager",
            role="manager",
            venue_id="venue-timeline-beta",
        )
        beta_headers = await login(
            client,
            beta_manager["username"],
            "Strong-Password-2026",
        )
        beta_event = await client.post(
            "/admin/events",
            headers=beta_headers,
            json={
                "raw_text": "南麓游客中心照明巡检待处理。",
                "event_type": "设施巡检",
                "severity": "P3",
                "from_user": beta_manager["id"],
            },
        )
        assert beta_event.status_code == 200, beta_event.text
        beta_event_id = beta_event.json()["event_id"]
        beta_detail = await client.get(
            f"/admin/events/{beta_event_id}",
            headers=beta_headers,
        )
        beta_hidden_from_alpha = await client.get(
            f"/admin/events/{beta_event_id}",
            headers=manager_headers,
        )
        alpha_hidden_from_beta = await client.get(
            f"/admin/events/{linked_event_id}",
            headers=beta_headers,
        )

    assert started.status_code == 200, started.text
    assert blocked.status_code == 200, blocked.text
    assert unblocked.status_code == 200, unblocked.text
    assert first_detail.status_code == 200, first_detail.text
    assert refreshed_detail.status_code == 200, refreshed_detail.text
    assert unrelated_detail.status_code == 200, unrelated_detail.text
    assert beta_detail.status_code == 200, beta_detail.text
    assert beta_hidden_from_alpha.status_code == 404
    assert alpha_hidden_from_beta.status_code == 404

    lifecycle = task_lifecycle_timeline(refreshed_detail.json()["dossier"])
    assert [entry["technical"]["activity_type"] for entry in lifecycle] == [
        "TASK_STARTED",
        "TASK_BLOCKED",
        "TASK_UNBLOCKED",
    ]
    assert [entry["label"] for entry in lifecycle] == [
        "任务已开始",
        "任务遇到现场阻碍",
        "任务阻碍已解除",
    ]
    assert [entry["summary"] for entry in lifecycle] == [
        "任务已开始执行。",
        "现场警戒带库存不足，需要仓库补充后继续。",
        "现场障碍已确认解决，任务已恢复推进。",
    ]
    assert [entry["actor_name"] for entry in lifecycle] == [
        "timeline-alpha-employee",
        "timeline-alpha-employee",
        "timeline-alpha-manager",
    ]
    assert {entry["business_id"] for entry in lifecycle} == {task_business_id}
    assert task_lifecycle_timeline(first_detail.json()["dossier"]) == lifecycle
    assert task_lifecycle_timeline(unrelated_detail.json()["dossier"]) == []
    assert task_lifecycle_timeline(beta_detail.json()["dossier"]) == []
    assert refreshed_detail.json()["dossier"]["tasks"][0]["block_reason"] is None
    await database.close()
