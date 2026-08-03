import httpx
import pytest

from src.memory_palace.api.v1.endpoints.assistant import router as assistant_router
from src.memory_palace.core.task_graph import TaskGraph
from tests.integration.test_mvp_business_apis import build_app, create_user, login


@pytest.mark.asyncio
async def test_employee_can_open_published_sop_reference(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        await create_user(
            client,
            admin_headers,
            username="sop-reference-employee",
            role="operator",
        )
        employee_headers = await login(
            client,
            "sop-reference-employee",
            "Strong-Password-2026",
        )
        created = await client.post(
            "/admin/sops",
            headers=admin_headers,
            json={
                "title": "观光车雨后复运与异常异响处置",
                "content": "保持车辆停运并隔离，保管钥匙，完成轮端检查前禁止载客。",
                "category": "设备安全",
                "priority": 1,
                "version": "2.1",
            },
        )
        assert created.status_code == 201, created.text
        sop_id = created.json()["sop"]["id"]
        submitted = await client.post(
            f"/admin/sops/{sop_id}/submit",
            headers=admin_headers,
        )
        published = await client.post(
            f"/admin/sops/{sop_id}/publish",
            headers=admin_headers,
            json={"comment": "知识负责人审核通过"},
        )
        reference = await client.get(
            f"/api/v1/assistant/knowledge/sops/{sop_id}?version=2.1",
            headers=employee_headers,
        )

    assert submitted.status_code == 200, submitted.text
    assert published.status_code == 200, published.text
    assert reference.status_code == 200, reference.text
    sop = reference.json()["sop"]
    assert sop == {
        "id": str(sop_id),
        "source_type": "SOP",
        "source_label": "已发布 SOP",
        "title": "观光车雨后复运与异常异响处置",
        "content": "保持车辆停运并隔离，保管钥匙，完成轮端检查前禁止载客。",
        "category": "设备安全",
        "version": "2.1",
        "status": "PUBLISHED",
        "status_label": "已发布",
        "publisher_name": "交付管理员",
        "published_at": sop["published_at"],
    }
    assert sop["published_at"] is not None

    await database.close()


@pytest.mark.asyncio
async def test_employee_sop_reference_hides_unpublished_foreign_and_wrong_version(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        await create_user(
            client,
            admin_headers,
            username="sop-scope-employee",
            role="operator",
        )
        employee_headers = await login(
            client,
            "sop-scope-employee",
            "Strong-Password-2026",
        )

        await database.execute(
            """
            INSERT INTO sop_documents (
                id, venue_id, category, title, content, version, status,
                reviewed_by, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3101,
                "venue-alpha",
                "设备安全",
                "尚未发布的车辆检查草稿",
                "草稿不得向员工公开。",
                "1.0",
                "DRAFT",
                None,
                None,
                1785283200.0,
                1785283200.0,
            ),
        )
        await database.execute(
            """
            INSERT INTO sop_documents (
                id, venue_id, category, title, content, version, status,
                reviewed_by, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?, ?, ?)
            """,
            (
                3102,
                "venue-beta",
                "设备安全",
                "其他场地已发布 SOP",
                "其他场地内容不得泄漏。",
                "1.0",
                None,
                1785283200.0,
                1785283200.0,
                1785283200.0,
            ),
        )
        await database.execute(
            """
            INSERT INTO sop_documents (
                id, venue_id, category, title, content, version, status,
                reviewed_by, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?, ?, ?)
            """,
            (
                3103,
                "venue-alpha",
                "设备安全",
                "当前版本 SOP",
                "员工只能打开卡片引用的明确版本。",
                "2.1",
                None,
                1785283200.0,
                1785283200.0,
                1785283200.0,
            ),
        )

        hidden = [
            await client.get(
                "/api/v1/assistant/knowledge/sops/3101?version=1.0",
                headers=employee_headers,
            ),
            await client.get(
                "/api/v1/assistant/knowledge/sops/3102?version=1.0",
                headers=employee_headers,
            ),
            await client.get(
                "/api/v1/assistant/knowledge/sops/3103?version=1.0",
                headers=employee_headers,
            ),
        ]
        admin_reads = [
            await client.get("/admin/sops", headers=employee_headers),
            await client.get("/admin/sops/3103", headers=employee_headers),
        ]

    assert all(response.status_code == 404 for response in hidden)
    assert all(
        response.json()["detail"]["code"] == "SOP_REFERENCE_NOT_FOUND"
        for response in hidden
    )
    assert all(response.status_code == 403 for response in admin_reads)
    assert all(
        response.json()["detail"]["code"] == "AUTH_FORBIDDEN"
        for response in admin_reads
    )

    await database.close()


@pytest.mark.asyncio
async def test_employee_work_list_contains_only_own_tasks_and_related_events(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="work-employee",
            role="operator",
        )
        colleague = await create_user(
            client,
            admin_headers,
            username="work-colleague",
            role="operator",
        )
        employee_headers = await login(
            client,
            "work-employee",
            "Strong-Password-2026",
        )

        own_task = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "work-session-own",
                "description": "复核东门客流疏导结果",
                "assigned_user_id": employee["id"],
            },
        )
        colleague_task = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "work-session-colleague",
                "description": "处理南门设备报修",
                "assigned_user_id": colleague["id"],
            },
        )
        unassigned_task = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "work-session-unassigned",
                "description": "等待值班经理分派",
            },
        )
        assert own_task.status_code == 201, own_task.text
        assert colleague_task.status_code == 201, colleague_task.text
        assert unassigned_task.status_code == 201, unassigned_task.text

        reported_event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "东门排队超过二十分钟，已启动分流。",
                "event_type": "客流拥堵",
                "severity": "P2",
                "from_user": employee["id"],
            },
        )
        assigned_event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "观光车站点有游客遗失物品。",
                "event_type": "游客服务",
                "severity": "P3",
                "from_user": colleague["id"],
            },
        )
        unrelated_event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "南门闸机需要更换扫码器。",
                "event_type": "设备故障",
                "severity": "P3",
                "from_user": colleague["id"],
            },
        )
        assert reported_event.status_code == 200, reported_event.text
        assert assigned_event.status_code == 200, assigned_event.text
        assert unrelated_event.status_code == 200, unrelated_event.text
        assigned_event_id = assigned_event.json()["event_id"]
        assignment = await client.patch(
            f"/admin/events/{assigned_event_id}",
            headers=admin_headers,
            json={"assigned_to": employee["id"]},
        )
        assert assignment.status_code == 200, assignment.text

        response = await client.get(
            "/api/v1/assistant/work",
            headers=employee_headers,
        )
        reported_detail = await client.get(
            f"/api/v1/assistant/work/events/{reported_event.json()['event_id']}",
            headers=employee_headers,
        )
        unrelated_detail = await client.get(
            f"/api/v1/assistant/work/events/{unrelated_event.json()['event_id']}",
            headers=employee_headers,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert {task["id"] for task in payload["tasks"]} == {
        own_task.json()["task"]["id"]
    }
    assert {event["event_id"] for event in payload["events"]} == {
        reported_event.json()["event_id"],
        assigned_event_id,
    }
    assert payload["limit"] == 100
    assert payload["offset"] == 0
    assert reported_detail.status_code == 200, reported_detail.text
    assert reported_detail.json()["event"]["business_id"].startswith("SJ-")
    assert unrelated_detail.status_code == 404, unrelated_detail.text

    await database.close()


@pytest.mark.asyncio
async def test_manual_block_cannot_be_bypassed_through_legacy_fail_action(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="block-bypass-employee",
            role="operator",
        )
        employee_headers = await login(
            client,
            "block-bypass-employee",
            "Strong-Password-2026",
        )
        created = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "block-bypass-session",
                "description": "等待工程人员提供绝缘工具后继续检修",
                "assigned_user_id": employee["id"],
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task"]["id"]
        started = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/start",
            headers=employee_headers,
        )
        blocked = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/block",
            headers=employee_headers,
            json={"reason": "缺少绝缘工具，继续操作存在安全风险。"},
        )
        assert started.status_code == 200, started.text
        assert blocked.status_code == 200, blocked.text

        bypass = await client.post(
            f"/admin/tasks/{task_id}/fail",
            headers=employee_headers,
            json={"error": "尝试绕过经理恢复流程"},
        )
        detail = await client.get(
            f"/api/v1/assistant/work/tasks/{task_id}",
            headers=employee_headers,
        )

    assert bypass.status_code == 409, bypass.text
    assert bypass.json()["detail"]["code"] == "TASK_NOT_RUNNING"
    assert detail.status_code == 200, detail.text
    assert detail.json()["task"]["status"] == "BLOCKED"
    assert detail.json()["task"]["block_reason"] == (
        "缺少绝缘工具，继续操作存在安全风险。"
    )

    await database.close()


@pytest.mark.asyncio
async def test_employee_task_result_and_block_reason_must_contain_readable_text(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="readable-text-employee",
            role="operator",
        )
        employee_headers = await login(
            client,
            "readable-text-employee",
            "Strong-Password-2026",
        )
        created = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "readable-text-session",
                "description": "反馈游客中心失物招领处理情况",
                "assigned_user_id": employee["id"],
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task"]["id"]
        started = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/start",
            headers=employee_headers,
        )
        assert started.status_code == 200, started.text

        empty_completion = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/complete",
            headers=employee_headers,
            json={"summary": "   "},
        )
        empty_block = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/block",
            headers=employee_headers,
            json={"reason": " \t "},
        )
        detail = await client.get(
            f"/api/v1/assistant/work/tasks/{task_id}",
            headers=employee_headers,
        )

    assert empty_completion.status_code == 422, empty_completion.text
    assert empty_block.status_code == 422, empty_block.text
    assert detail.status_code == 200, detail.text
    assert detail.json()["task"]["status"] == "RUNNING"
    assert detail.json()["task"]["result"] is None
    assert detail.json()["task"]["block_reason"] is None

    await database.close()


@pytest.mark.asyncio
async def test_employee_work_actions_hide_other_people_and_other_tenants_tasks(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        venue = await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-beta", "name": "南麓游客中心"},
        )
        assert venue.status_code == 201, venue.text
        employee = await create_user(
            client,
            admin_headers,
            username="scope-employee",
            role="operator",
        )
        colleague = await create_user(
            client,
            admin_headers,
            username="scope-colleague",
            role="operator",
        )
        beta_manager = await create_user(
            client,
            admin_headers,
            username="scope-beta-manager",
            role="manager",
            venue_id="venue-beta",
        )
        beta_employee = await create_user(
            client,
            admin_headers,
            username="scope-beta-employee",
            role="operator",
            venue_id="venue-beta",
        )
        employee_headers = await login(
            client,
            "scope-employee",
            "Strong-Password-2026",
        )
        beta_manager_headers = await login(
            client,
            "scope-beta-manager",
            "Strong-Password-2026",
        )
        colleague_task = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "scope-colleague-session",
                "description": "同场地其他员工任务",
                "assigned_user_id": colleague["id"],
            },
        )
        beta_task = await client.post(
            "/admin/tasks",
            headers=beta_manager_headers,
            json={
                "session_id": "scope-beta-session",
                "description": "其他场地员工任务",
                "assigned_user_id": beta_employee["id"],
            },
        )
        assert colleague_task.status_code == 201, colleague_task.text
        assert beta_task.status_code == 201, beta_task.text

        forbidden_responses = []
        for task_id in (
            colleague_task.json()["task"]["id"],
            beta_task.json()["task"]["id"],
        ):
            forbidden_responses.extend(
                (
                    await client.get(
                        f"/api/v1/assistant/work/tasks/{task_id}",
                        headers=employee_headers,
                    ),
                    await client.post(
                        f"/api/v1/assistant/work/tasks/{task_id}/start",
                        headers=employee_headers,
                    ),
                    await client.post(
                        f"/api/v1/assistant/work/tasks/{task_id}/complete",
                        headers=employee_headers,
                        json={"summary": "不应被接受的完成结果"},
                    ),
                    await client.post(
                        f"/api/v1/assistant/work/tasks/{task_id}/block",
                        headers=employee_headers,
                        json={"reason": "不应被接受的阻塞原因"},
                    ),
                )
            )

        colleague_after = await client.get(
            f"/admin/tasks/{colleague_task.json()['task']['id']}",
            headers=admin_headers,
        )
        beta_after = await client.get(
            f"/admin/tasks/{beta_task.json()['task']['id']}",
            headers=beta_manager_headers,
        )

    assert all(response.status_code == 404 for response in forbidden_responses)
    assert all(
        response.json()["detail"]["code"] == "TASK_NOT_FOUND"
        for response in forbidden_responses
    )
    assert colleague_after.json()["task"]["status"] == "PENDING"
    assert beta_after.json()["task"]["status"] == "PENDING"

    await database.close()


@pytest.mark.asyncio
async def test_legacy_admin_event_routes_require_management_role(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="legacy-event-employee",
            role="operator",
        )
        employee_headers = await login(
            client,
            "legacy-event-employee",
            "Strong-Password-2026",
        )
        created = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "员工通道门禁失灵，已安排专人值守。",
                "event_type": "设备故障",
                "severity": "P2",
                "from_user": employee["id"],
            },
        )
        assert created.status_code == 200, created.text
        event_id = created.json()["event_id"]

        employee_responses = [
            await client.get("/admin/events", headers=employee_headers),
            await client.get(f"/admin/events/{event_id}", headers=employee_headers),
            await client.post(
                "/admin/events",
                headers=employee_headers,
                json={
                    "raw_text": "普通员工不应通过管理端录入事件。",
                    "event_type": "权限测试",
                    "severity": "P3",
                    "from_user": employee["id"],
                },
            ),
            await client.patch(
                f"/admin/events/{event_id}",
                headers=employee_headers,
                json={"severity": "P1"},
            ),
            await client.post(
                f"/admin/events/{event_id}/close",
                headers=employee_headers,
                json={"resolution": "普通员工不应通过管理端关闭事件。"},
            ),
        ]

        admin_list = await client.get("/admin/events", headers=admin_headers)
        admin_detail = await client.get(
            f"/admin/events/{event_id}",
            headers=admin_headers,
        )
        admin_updated = await client.patch(
            f"/admin/events/{event_id}",
            headers=admin_headers,
            json={"severity": "P1"},
        )
        admin_closed = await client.post(
            f"/admin/events/{event_id}/close",
            headers=admin_headers,
            json={"resolution": "门禁控制器已更换并完成三轮开关测试。"},
        )

    assert all(response.status_code == 403 for response in employee_responses)
    assert all(
        response.json()["detail"]["code"] == "AUTH_FORBIDDEN"
        for response in employee_responses
    )
    assert admin_list.status_code == 200, admin_list.text
    assert event_id in {event["event_id"] for event in admin_list.json()["events"]}
    assert admin_detail.status_code == 200, admin_detail.text
    assert admin_updated.status_code == 200, admin_updated.text
    assert admin_closed.status_code == 200, admin_closed.text

    await database.close()


@pytest.mark.asyncio
async def test_legacy_admin_task_reads_cannot_bypass_employee_scope(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="legacy-task-employee",
            role="operator",
        )
        colleague = await create_user(
            client,
            admin_headers,
            username="legacy-task-colleague",
            role="operator",
        )
        employee_headers = await login(
            client,
            "legacy-task-employee",
            "Strong-Password-2026",
        )
        created_tasks = []
        for session_id, description, assignee in (
            ("legacy-own", "本人负责的任务", employee["id"]),
            ("legacy-other", "其他员工负责的任务", colleague["id"]),
            ("legacy-unassigned", "尚未分派的任务", None),
        ):
            response = await client.post(
                "/admin/tasks",
                headers=admin_headers,
                json={
                    "session_id": session_id,
                    "description": description,
                    "assigned_user_id": assignee,
                },
            )
            assert response.status_code == 201, response.text
            created_tasks.append(response.json()["task"])

        employee_list = await client.get("/admin/tasks", headers=employee_headers)
        employee_other_detail = await client.get(
            f"/admin/tasks/{created_tasks[1]['id']}",
            headers=employee_headers,
        )
        admin_list = await client.get("/admin/tasks", headers=admin_headers)
        admin_other_detail = await client.get(
            f"/admin/tasks/{created_tasks[1]['id']}",
            headers=admin_headers,
        )

    assert employee_list.status_code == 200, employee_list.text
    assert {task["id"] for task in employee_list.json()["tasks"]} == {
        created_tasks[0]["id"]
    }
    assert employee_other_detail.status_code == 404, employee_other_detail.text
    assert employee_other_detail.json()["detail"]["code"] == "TASK_NOT_FOUND"
    assert admin_list.status_code == 200, admin_list.text
    assert {task["id"] for task in admin_list.json()["tasks"]} == {
        task["id"] for task in created_tasks
    }
    assert admin_other_detail.status_code == 200, admin_other_detail.text

    await database.close()


@pytest.mark.asyncio
async def test_employee_block_reason_survives_restart_until_manager_resumes_task(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="blocked-employee",
            role="operator",
        )
        employee_headers = await login(
            client,
            "blocked-employee",
            "Strong-Password-2026",
        )
        created = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "blocked-session",
                "description": "拍摄北门受损护栏并设置警戒线",
                "assigned_user_id": employee["id"],
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task"]["id"]
        started = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/start",
            headers=employee_headers,
        )
        assert started.status_code == 200, started.text

        blocked = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/block",
            headers=employee_headers,
            json={"reason": "现场警戒带库存不足，需要仓库补充后继续。"},
        )

        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["task"]["status"] == "BLOCKED"
        assert blocked.json()["task"]["block_reason"] == (
            "现场警戒带库存不足，需要仓库补充后继续。"
        )

        restarted_graph = TaskGraph(database)
        await restarted_graph.reload_from_db()
        app.state.task_graph = restarted_graph

        after_restart = await client.get(
            f"/api/v1/assistant/work/tasks/{task_id}",
            headers=employee_headers,
        )
        admin_detail = await client.get(
            f"/admin/tasks/{task_id}",
            headers=admin_headers,
        )
        resumed = await client.post(
            f"/admin/tasks/{task_id}/unblock",
            headers=admin_headers,
        )

    assert after_restart.status_code == 200, after_restart.text
    assert after_restart.json()["task"]["status"] == "BLOCKED"
    assert after_restart.json()["task"]["block_reason"] == (
        "现场警戒带库存不足，需要仓库补充后继续。"
    )
    assert admin_detail.status_code == 200, admin_detail.text
    assert admin_detail.json()["task"]["block_reason"] == (
        "现场警戒带库存不足，需要仓库补充后继续。"
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["task"]["status"] == "PENDING"
    assert resumed.json()["task"]["block_reason"] is None

    await database.close()


@pytest.mark.asyncio
async def test_employee_can_start_and_complete_own_task_with_readable_result(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="complete-employee",
            role="operator",
        )
        employee_headers = await login(
            client,
            "complete-employee",
            "Strong-Password-2026",
        )
        created = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "complete-session",
                "description": "完成西门闭园前安全巡查",
                "assigned_user_id": employee["id"],
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task"]["id"]

        started = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/start",
            headers=employee_headers,
        )
        completed = await client.post(
            f"/api/v1/assistant/work/tasks/{task_id}/complete",
            headers=employee_headers,
            json={"summary": "西门闸机、消防通道和应急照明均已复核，无异常。"},
        )
        detail = await client.get(
            f"/api/v1/assistant/work/tasks/{task_id}",
            headers=employee_headers,
        )

    assert started.status_code == 200, started.text
    assert started.json()["task"]["status"] == "RUNNING"
    assert completed.status_code == 200, completed.text
    assert completed.json()["task"]["status"] == "DONE"
    assert completed.json()["task"]["result"] == {
        "summary": "西门闸机、消防通道和应急照明均已复核，无异常。"
    }
    assert detail.status_code == 200, detail.text
    assert detail.json()["task"]["result"] == completed.json()["task"]["result"]

    await database.close()


@pytest.mark.asyncio
async def test_employee_can_open_only_own_task_detail(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.include_router(assistant_router, prefix="/api/v1/assistant")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        employee = await create_user(
            client,
            admin_headers,
            username="detail-employee",
            role="operator",
        )
        colleague = await create_user(
            client,
            admin_headers,
            username="detail-colleague",
            role="operator",
        )
        employee_headers = await login(
            client,
            "detail-employee",
            "Strong-Password-2026",
        )
        own_task = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "detail-session-own",
                "description": "确认接驳车末班车到站时间",
                "assigned_user_id": employee["id"],
            },
        )
        colleague_task = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "detail-session-colleague",
                "description": "检查游客中心广播设备",
                "assigned_user_id": colleague["id"],
            },
        )
        assert own_task.status_code == 201, own_task.text
        assert colleague_task.status_code == 201, colleague_task.text

        own_response = await client.get(
            f"/api/v1/assistant/work/tasks/{own_task.json()['task']['id']}",
            headers=employee_headers,
        )
        colleague_response = await client.get(
            f"/api/v1/assistant/work/tasks/{colleague_task.json()['task']['id']}",
            headers=employee_headers,
        )
        unauthenticated_response = await client.get(
            f"/api/v1/assistant/work/tasks/{own_task.json()['task']['id']}"
        )

    assert own_response.status_code == 200, own_response.text
    assert own_response.json()["task"]["description"] == "确认接驳车末班车到站时间"
    assert colleague_response.status_code == 404, colleague_response.text
    assert colleague_response.json()["detail"]["code"] == "TASK_NOT_FOUND"
    assert unauthenticated_response.status_code == 401, unauthenticated_response.text
    assert unauthenticated_response.json()["detail"]["code"] == "AUTH_REQUIRED"

    await database.close()
