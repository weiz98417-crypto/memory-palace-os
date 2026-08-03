import asyncio
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.memory_palace.core.task_graph import TaskGraph, TaskStatus
from tests.integration.test_mvp_business_apis import build_app, create_user, login


class TodoLLMStub:
    def __init__(self, payload):
        self.payload = payload
        self.ask = AsyncMock(
            return_value=SimpleNamespace(
                content=json.dumps(payload, ensure_ascii=False),
                tokens_used=37,
            )
        )
        self.parse_json = AsyncMock(return_value=payload)


class BlockingTodoLLMStub:
    def __init__(self, payload):
        self.payload = payload
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.ask = AsyncMock(side_effect=self._ask)
        self.parse_json = AsyncMock(return_value=payload)

    async def _ask(self, **kwargs):
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(
            content=json.dumps(self.payload, ensure_ascii=False),
            tokens_used=37,
        )


async def insert_session(database, *, session_id, user_id, venue_id):
    now = time.time()
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, stage, created_at, updated_at
        ) VALUES (?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (session_id, user_id, venue_id, now, now),
    )


@pytest.mark.asyncio
async def test_manual_task_creation_links_tenant_event_and_returns_business_id(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "东门观光车右后轮出现间歇性异响",
                "event_type": "观光车设备异常",
                "severity": "P1",
                "from_user": "现场员工李明",
            },
        )
        assert event.status_code == 200, event.text
        event_id = event.json()["event_id"]

        created = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "session-linked-manual-task",
                "event_id": event_id,
                "description": "隔离 12 号观光车并上传现场照片",
            },
        )
        assert created.status_code == 201, created.text
        task = created.json()["task"]

        detail = await client.get(f"/admin/tasks/{task['id']}", headers=admin_headers)

    assert task["business_id"].startswith("RW-")
    assert task["event_id"] == event_id
    assert detail.status_code == 200, detail.text
    assert detail.json()["task"]["business_id"] == task["business_id"]
    assert detail.json()["task"]["event_id"] == event_id

    audit = await database.fetch_one(
        """
        SELECT metadata_json FROM audit_logs
        WHERE action = 'TASK_CREATED' AND resource_id = ?
        """,
        (task["id"],),
    )
    metadata = json.loads(audit["metadata_json"])
    assert metadata["business_id"] == task["business_id"]
    assert metadata["event_id"] == event_id
    activity = await database.fetch_one(
        """
        SELECT activity_type, payload_json FROM event_activities
        WHERE venue_id = ? AND event_id = ? AND idempotency_key = ?
        """,
        ("venue-alpha", event_id, f"task-created:{task['id']}"),
    )
    assert activity["activity_type"] == "TASK_CREATED"
    activity_payload = json.loads(activity["payload_json"])
    assert activity_payload["business_id"] == task["business_id"]
    assert activity_payload["title"] == task["description"]
    await database.close()


@pytest.mark.asyncio
async def test_manual_task_creation_rolls_back_when_event_activity_persistence_fails(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "东门观光车右后轮异响需要派发人工任务",
                "event_type": "观光车设备异常",
                "severity": "P1",
                "from_user": "现场员工李明",
            },
        )
        assert event.status_code == 200, event.text
        event_id = event.json()["event_id"]

        original_execute = database.execute

        async def fail_task_activity_insert(sql, parameters=()):
            if "INSERT INTO event_activities" in sql:
                raise RuntimeError("injected event activity persistence failure")
            return await original_execute(sql, parameters)

        monkeypatch.setattr(database, "execute", fail_task_activity_insert)
        response = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "session-manual-task-rollback",
                "event_id": event_id,
                "description": "隔离车辆并记录右后轮检测结果",
            },
        )

    assert response.status_code == 500, response.text
    assert response.json()["detail"]["code"] == "TASK_CREATION_PERSISTENCE_FAILED"
    assert await database.fetch_one(
        "SELECT id FROM tasks WHERE session_id = ?",
        ("session-manual-task-rollback",),
    ) is None
    assert await app.state.task_graph.get_session_tasks(
        "session-manual-task-rollback"
    ) == []
    assert await database.fetch_one(
        """
        SELECT id FROM audit_logs
        WHERE venue_id = ? AND action = 'TASK_CREATED'
          AND resource_type = 'task'
          AND json_extract(metadata_json, '$.session_id') = ?
        """,
        ("venue-alpha", "session-manual-task-rollback"),
    ) is None
    assert await database.fetch_one(
        """
        SELECT id FROM event_activities
        WHERE venue_id = ? AND event_id = ? AND activity_type = 'TASK_CREATED'
        """,
        ("venue-alpha", event_id),
    ) is None
    await database.close()


@pytest.mark.asyncio
async def test_manual_task_creation_rejects_missing_and_cross_tenant_events_without_writes(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        venue = await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-task-beta", "name": "南麓景区"},
        )
        assert venue.status_code == 201, venue.text
        beta_manager = await create_user(
            client,
            admin_headers,
            username="task-beta-manager",
            role="manager",
            venue_id="venue-task-beta",
        )
        beta_headers = await login(client, "task-beta-manager", "Strong-Password-2026")
        beta_event = await client.post(
            "/admin/events",
            headers=beta_headers,
            json={
                "raw_text": "南麓景区设备异常",
                "event_type": "跨场地测试事件",
                "severity": "P2",
                "from_user": beta_manager["id"],
            },
        )
        assert beta_event.status_code == 200, beta_event.text

        missing = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "session-task-event-denied",
                "event_id": "missing-event-id",
                "description": "不应创建的缺失事件任务",
            },
        )
        cross_tenant = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "session-task-event-denied",
                "event_id": beta_event.json()["event_id"],
                "description": "不应创建的跨场地任务",
            },
        )

    for response in (missing, cross_tenant):
        assert response.status_code == 404, response.text
        assert response.json()["detail"]["code"] == "EVENT_NOT_FOUND"
    assert await database.fetch_one(
        "SELECT id FROM tasks WHERE session_id = ?",
        ("session-task-event-denied",),
    ) is None
    await database.close()


@pytest.mark.asyncio
async def test_decomposition_links_event_to_every_business_task_and_timeline(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.skills.todo.skill.llm_client",
        TodoLLMStub(
            {
                "tasks": [
                    {"description": "隔离 12 号观光车", "depends_on": []},
                    {"description": "检查右后轮并记录测量值", "depends_on": [0]},
                ]
            }
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await insert_session(
            database,
            session_id="session-linked-decomposition",
            user_id=admin["id"],
            venue_id="venue-alpha",
        )
        event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "12 号观光车右后轮出现异响",
                "event_type": "观光车设备异常",
                "severity": "P1",
                "from_user": "现场员工李明",
            },
        )
        assert event.status_code == 200, event.text
        event_id = event.json()["event_id"]

        response = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "linked-event-decompose-001"},
            json={
                "goal": "完成车辆隔离和右后轮检查",
                "session_id": "session-linked-decomposition",
                "event_id": event_id,
            },
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["event_id"] == event_id
    assert {task["event_id"] for task in payload["tasks"]} == {event_id}
    assert all(task["business_id"].startswith("RW-") for task in payload["tasks"])

    decomposition = await database.fetch_one(
        "SELECT event_id FROM task_decompositions WHERE decomposition_id = ?",
        (payload["decomposition_id"],),
    )
    assert decomposition["event_id"] == event_id
    activities = await database.fetch_all(
        """
        SELECT activity_type, payload_json FROM event_activities
        WHERE venue_id = ? AND event_id = ? AND trace_id = ?
        ORDER BY created_at, activity_type
        """,
        ("venue-alpha", event_id, payload["trace_id"]),
    )
    assert [activity["activity_type"] for activity in activities].count("TASK_CREATED") == 2
    assert [activity["activity_type"] for activity in activities].count("TASK_DECOMPOSED") == 1
    created_payloads = [
        json.loads(activity["payload_json"])
        for activity in activities
        if activity["activity_type"] == "TASK_CREATED"
    ]
    assert {item["business_id"] for item in created_payloads} == {
        task["business_id"] for task in payload["tasks"]
    }
    assert {item["title"] for item in created_payloads} == {
        task["description"] for task in payload["tasks"]
    }
    await database.close()


@pytest.mark.asyncio
async def test_decomposition_rejects_missing_and_cross_tenant_events_before_model_call(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    llm = TodoLLMStub(
        {"tasks": [{"description": "不应生成的任务", "depends_on": []}]}
    )
    monkeypatch.setattr("src.memory_palace.skills.todo.skill.llm_client", llm)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await insert_session(
            database,
            session_id="session-decompose-event-denied",
            user_id=admin["id"],
            venue_id="venue-alpha",
        )
        venue = await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-decompose-beta", "name": "北岭景区"},
        )
        assert venue.status_code == 201, venue.text
        beta_manager = await create_user(
            client,
            admin_headers,
            username="decompose-beta-manager",
            role="manager",
            venue_id="venue-decompose-beta",
        )
        beta_headers = await login(client, "decompose-beta-manager", "Strong-Password-2026")
        beta_event = await client.post(
            "/admin/events",
            headers=beta_headers,
            json={
                "raw_text": "北岭景区设备异常",
                "event_type": "跨场地分解测试事件",
                "severity": "P2",
                "from_user": beta_manager["id"],
            },
        )
        assert beta_event.status_code == 200, beta_event.text

        missing = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "missing-event-decompose-001"},
            json={
                "goal": "不应为缺失事件生成任务",
                "session_id": "session-decompose-event-denied",
                "event_id": "missing-event-id",
            },
        )
        cross_tenant = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "cross-event-decompose-001"},
            json={
                "goal": "不应为跨场地事件生成任务",
                "session_id": "session-decompose-event-denied",
                "event_id": beta_event.json()["event_id"],
            },
        )

    for response in (missing, cross_tenant):
        assert response.status_code == 404, response.text
        assert response.json()["detail"]["code"] == "EVENT_NOT_FOUND"
    llm.ask.assert_not_awaited()
    assert await database.fetch_one(
        "SELECT id FROM tasks WHERE session_id = ?",
        ("session-decompose-event-denied",),
    ) is None
    await database.close()


@pytest.mark.asyncio
async def test_event_linked_decomposition_failure_audit_keeps_event_id(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.skills.todo.skill.llm_client",
        TodoLLMStub(
            {
                "tasks": [
                    {"description": "包含非法未来依赖的任务", "depends_on": [1]},
                ]
            }
        ),
    )
    admin = await database.fetch_one(
        "SELECT id FROM users WHERE username = ?",
        ("mvp-admin",),
    )
    await insert_session(
        database,
        session_id="session-event-linked-failure-audit",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "设备异常需要分解，但模型返回非法任务结构",
                "event_type": "设备异常",
                "severity": "P1",
                "from_user": admin["id"],
            },
        )
        assert event.status_code == 200, event.text
        event_id = event.json()["event_id"]
        response = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "event-failure-audit-001"},
            json={
                "goal": "为当前设备异常生成处置任务",
                "session_id": "session-event-linked-failure-audit",
                "event_id": event_id,
            },
        )

    try:
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["code"] == "TASK_DECOMPOSITION_FAILED"
        audit = await database.fetch_one(
            """
            SELECT metadata_json FROM audit_logs
            WHERE venue_id = ? AND action = 'TASK_DECOMPOSITION_FAILED'
              AND resource_type = 'session' AND resource_id = ?
            """,
            ("venue-alpha", "session-event-linked-failure-audit"),
        )
        assert json.loads(audit["metadata_json"])["event_id"] == event_id
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_decomposition_idempotency_key_cannot_move_task_graph_to_another_event(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    llm = TodoLLMStub(
        {"tasks": [{"description": "核查当前事件现场", "depends_on": []}]}
    )
    monkeypatch.setattr("src.memory_palace.skills.todo.skill.llm_client", llm)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await insert_session(
            database,
            session_id="session-event-fingerprint",
            user_id=admin["id"],
            venue_id="venue-alpha",
        )
        event_ids = []
        for index in (1, 2):
            event = await client.post(
                "/admin/events",
                headers=admin_headers,
                json={
                    "raw_text": f"第 {index} 条独立现场事件",
                    "event_type": "任务幂等测试事件",
                    "severity": "P2",
                    "from_user": admin["id"],
                },
            )
            assert event.status_code == 200, event.text
            event_ids.append(event.json()["event_id"])

        request_body = {
            "goal": "为当前事件生成核查任务",
            "session_id": "session-event-fingerprint",
            "event_id": event_ids[0],
        }
        first = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "event-fingerprint-001"},
            json=request_body,
        )
        moved = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "event-fingerprint-001"},
            json={**request_body, "event_id": event_ids[1]},
        )

    assert first.status_code == 201, first.text
    assert moved.status_code == 409, moved.text
    assert moved.json()["detail"]["code"] == "TASK_IDEMPOTENCY_KEY_REUSED"
    llm.ask.assert_awaited_once()
    rows = await database.fetch_all(
        "SELECT event_id FROM tasks WHERE session_id = ?",
        ("session-event-fingerprint",),
    )
    assert [row["event_id"] for row in rows] == [event_ids[0]]
    await database.close()


@pytest.mark.asyncio
async def test_unlinked_decomposition_replays_legacy_idempotency_fingerprint(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    llm = TodoLLMStub(
        {"tasks": [{"description": "不应重新生成的任务", "depends_on": []}]}
    )
    monkeypatch.setattr("src.memory_palace.skills.todo.skill.llm_client", llm)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    session_id = "session-legacy-fingerprint"
    idempotency_key = "legacy-fingerprint-001"
    goal = "恢复升级前已完成的任务分解"
    admin = await database.fetch_one(
        "SELECT id FROM users WHERE username = ?",
        ("mvp-admin",),
    )
    await insert_session(
        database,
        session_id=session_id,
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    legacy_fingerprint_payload = {
        "assigned_user_id": None,
        "goal": goal,
        "max_attempts": 3,
        "session_id": session_id,
    }
    legacy_fingerprint = hashlib.sha256(
        json.dumps(
            legacy_fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    original_result = {
        "status": "created",
        "trace_id": "trace-legacy-fingerprint",
        "decomposition_id": "decomposition-legacy-fingerprint",
        "idempotency_key": idempotency_key,
        "agent_id": "TodoWrite",
        "session_id": session_id,
        "tasks_created": 1,
        "tasks": [{"business_id": "RW-20260730-LEGACY01", "description": "历史任务"}],
    }
    now = time.time()
    await database.execute(
        """
        INSERT INTO task_decompositions (
            decomposition_id, venue_id, requested_by, idempotency_key,
            request_fingerprint, session_id, trace_id, status, task_ids,
            response_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'COMPLETED', '[]', ?, NULL, ?, ?)
        """,
        (
            original_result["decomposition_id"],
            "venue-alpha",
            admin["id"],
            idempotency_key,
            legacy_fingerprint,
            session_id,
            original_result["trace_id"],
            json.dumps(original_result, ensure_ascii=False),
            now,
            now,
        ),
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        replayed = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": idempotency_key},
            json={"goal": goal, "session_id": session_id},
        )

    assert replayed.status_code == 201, replayed.text
    assert replayed.json() == original_result
    llm.ask.assert_not_awaited()
    await database.close()


@pytest.mark.asyncio
async def test_decompose_tasks_creates_tenant_scoped_graph_and_audit(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    llm = TodoLLMStub(
        {
            "tasks": [
                {"description": "核对节假日客流预测", "depends_on": []},
                {"description": "检查重点设备", "depends_on": []},
                {"description": "形成联合检查清单", "depends_on": [0, 1]},
            ]
        }
    )
    monkeypatch.setattr("src.memory_palace.skills.todo.skill.llm_client", llm)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        assignee = await create_user(
            client,
            admin_headers,
            username="todo-operator",
            role="operator",
        )
        admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
        await insert_session(
            database,
            session_id="session-todo-success",
            user_id=admin["id"],
            venue_id="venue-alpha",
        )

        response = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "todo-success-001"},
            json={
                "goal": "完成景区节假日前安全检查",
                "session_id": "session-todo-success",
                "assigned_user_id": assignee["id"],
                "max_attempts": 5,
                "venue_id": "venue-beta",
            },
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "created"
    assert payload["agent_id"] == "TodoWrite"
    assert payload["session_id"] == "session-todo-success"
    assert payload["tasks_created"] == 3
    assert len(payload["tasks"]) == 3
    assert {task["venue_id"] for task in payload["tasks"]} == {"venue-alpha"}
    assert {task["assigned_user_id"] for task in payload["tasks"]} == {assignee["id"]}
    assert {task["max_attempts"] for task in payload["tasks"]} == {5}
    assert payload["tasks"][2]["dependencies"] == [
        payload["tasks"][0]["id"],
        payload["tasks"][1]["id"],
    ]
    assert payload["tasks"][2]["status"] == TaskStatus.BLOCKED.value

    llm.ask.assert_awaited_once()
    llm_context = llm.ask.await_args.kwargs
    assert llm_context["venue_id"] == "venue-alpha"
    assert llm_context["agent_id"] == "TodoWrite"

    audit_rows = await database.fetch_all(
        "SELECT action, outcome, trace_id, metadata_json FROM audit_logs WHERE trace_id = ? ORDER BY id",
        (payload["trace_id"],),
    )
    assert [row["action"] for row in audit_rows] == [
        "TASK_CREATED",
        "TASK_CREATED",
        "TASK_CREATED",
        "TASK_DECOMPOSED",
    ]
    assert {row["outcome"] for row in audit_rows} == {"SUCCEEDED"}
    assert {row["trace_id"] for row in audit_rows} == {payload["trace_id"]}
    assert json.loads(audit_rows[-1]["metadata_json"])["tasks_created"] == 3
    await database.close()


@pytest.mark.asyncio
async def test_decomposition_replay_status_and_requester_scope(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    llm = TodoLLMStub(
        {
            "tasks": [
                {"description": "恢复前置任务", "depends_on": []},
                {"description": "恢复后继任务", "depends_on": [0]},
            ]
        }
    )
    monkeypatch.setattr("src.memory_palace.skills.todo.skill.llm_client", llm)
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-todo-status-recovery",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    request_body = {
        "goal": "验证客户端中断后的任务拆解恢复",
        "session_id": "session-todo-status-recovery",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        other_manager = await create_user(
            client,
            admin_headers,
            username="todo-recovery-manager",
            role="manager",
        )
        idempotent_headers = {
            **admin_headers,
            "Idempotency-Key": "todo-status-recovery-001",
        }
        created = await client.post(
            "/admin/tasks/decompose",
            headers=idempotent_headers,
            json=request_body,
        )
        replayed = await client.post(
            "/admin/tasks/decompose",
            headers=idempotent_headers,
            json=request_body,
        )
        recovered = await client.get(
            "/admin/tasks/decompositions/status",
            headers=admin_headers,
            params={"idempotency_key": "todo-status-recovery-001"},
        )
        other_headers = await login(
            client,
            other_manager["username"],
            "Strong-Password-2026",
        )
        hidden_from_other_requester = await client.get(
            "/admin/tasks/decompositions/status",
            headers=other_headers,
            params={"idempotency_key": "todo-status-recovery-001"},
        )
        missing_key = await client.post(
            "/admin/tasks/decompose",
            headers=admin_headers,
            json=request_body,
        )

    assert created.status_code == 201, created.text
    assert replayed.status_code == 201, replayed.text
    assert replayed.json() == created.json()
    assert recovered.status_code == 200, recovered.text
    assert recovered.json() == {
        "status": "COMPLETED",
        "decomposition_id": created.json()["decomposition_id"],
        "idempotency_key": "todo-status-recovery-001",
        "trace_id": created.json()["trace_id"],
        "retryable": False,
        "result": created.json(),
        "error": None,
    }
    assert hidden_from_other_requester.status_code == 404
    assert hidden_from_other_requester.json()["detail"]["code"] == "TASK_DECOMPOSITION_NOT_FOUND"
    assert missing_key.status_code == 422
    assert missing_key.json()["detail"]["code"] == "TASK_IDEMPOTENCY_KEY_INVALID"
    task_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM tasks WHERE session_id = ?",
        ("session-todo-status-recovery",),
    )
    assert task_count["total"] == 2
    llm.ask.assert_awaited_once()
    await database.close()


@pytest.mark.asyncio
async def test_concurrent_same_key_returns_processing_and_rejects_new_fingerprint(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    llm = BlockingTodoLLMStub(
        {"tasks": [{"description": "并发场景唯一任务", "depends_on": []}]}
    )
    monkeypatch.setattr("src.memory_palace.skills.todo.skill.llm_client", llm)
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-todo-concurrent",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    request_body = {
        "goal": "验证同一请求不会重复创建任务",
        "session_id": "session-todo-concurrent",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        headers = {**admin_headers, "Idempotency-Key": "todo-concurrent-001"}
        first_request = asyncio.create_task(
            client.post("/admin/tasks/decompose", headers=headers, json=request_body)
        )
        await asyncio.wait_for(llm.started.wait(), timeout=2)
        processing = await client.post(
            "/admin/tasks/decompose",
            headers=headers,
            json=request_body,
        )
        conflict = await client.post(
            "/admin/tasks/decompose",
            headers=headers,
            json={**request_body, "goal": "复用同一个键的不同目标"},
        )
        status_response = await client.get(
            "/admin/tasks/decompositions/status",
            headers=admin_headers,
            params={"idempotency_key": "todo-concurrent-001"},
        )
        llm.release.set()
        created = await asyncio.wait_for(first_request, timeout=2)

    assert processing.status_code == 202, processing.text
    assert processing.json()["status"] == "PROCESSING"
    assert processing.json()["retryable"] is True
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "PROCESSING"
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "TASK_IDEMPOTENCY_KEY_REUSED"
    assert created.status_code == 201, created.text
    llm.ask.assert_awaited_once()
    task_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM tasks WHERE session_id = ?",
        ("session-todo-concurrent",),
    )
    assert task_count["total"] == 1
    await database.close()


@pytest.mark.asyncio
async def test_status_expires_processing_lease_and_cleans_staged_orphans(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    graph = app.state.task_graph
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-todo-expired",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    decomposition_id = "decomposition-expired-001"
    orphan = await graph.create_task(
        "session-todo-expired",
        "不应暴露的中断任务",
        venue_id="venue-alpha",
        defer_activation=True,
        decomposition_id=decomposition_id,
    )
    expired_at = time.time() - 301
    await database.execute(
        """
        INSERT INTO task_decompositions (
            decomposition_id, venue_id, requested_by, idempotency_key,
            request_fingerprint, session_id, trace_id, status, task_ids,
            response_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?, NULL, NULL, ?, ?)
        """,
        (
            decomposition_id,
            "venue-alpha",
            admin["id"],
            "todo-expired-001",
            "unused-status-only-fingerprint",
            "session-todo-expired",
            "trace-expired-owner",
            json.dumps([orphan.id]),
            expired_at,
            expired_at,
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        expired = await client.get(
            "/admin/tasks/decompositions/status",
            headers=admin_headers,
            params={"idempotency_key": "todo-expired-001"},
        )

    assert expired.status_code == 200, expired.text
    assert expired.json()["status"] == "FAILED"
    assert expired.json()["retryable"] is True
    assert expired.json()["error"] == "processing_lease_expired"
    assert await graph.get_task(orphan.id) is None
    persisted = await database.fetch_one("SELECT id FROM tasks WHERE id = ?", (orphan.id,))
    assert persisted is None
    await database.close()


@pytest.mark.asyncio
async def test_status_cleanup_uses_persisted_task_ids_and_preserves_trace(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    graph = app.state.task_graph
    admin = await database.fetch_one(
        "SELECT id FROM users WHERE username = ?",
        ("mvp-admin",),
    )
    decomposition_id = "decomposition-partial-status-cleanup"
    original_trace_id = "trace-partial-status-cleanup"
    missing_task_id = "missing-staged-task-from-persisted-list"
    orphan = await graph.create_task(
        "session-partial-status-cleanup",
        "仍存在的暂存任务",
        venue_id="venue-alpha",
        defer_activation=True,
        decomposition_id=decomposition_id,
    )
    expired_at = time.time() - 301
    await database.execute(
        """
        INSERT INTO task_decompositions (
            decomposition_id, venue_id, requested_by, idempotency_key,
            request_fingerprint, session_id, trace_id, status, task_ids,
            response_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?, NULL, NULL, ?, ?)
        """,
        (
            decomposition_id,
            "venue-alpha",
            admin["id"],
            "partial-status-cleanup-001",
            "unused-partial-status-fingerprint",
            "session-partial-status-cleanup",
            original_trace_id,
            json.dumps([orphan.id, missing_task_id]),
            expired_at,
            expired_at,
        ),
    )
    audit_resources = [
        ("TASK_CREATED", "task", orphan.id),
        ("TASK_CREATED", "task", missing_task_id),
        ("TASK_DECOMPOSED", "task_decomposition", decomposition_id),
        ("TASK_CREATED", "task", "unrelated-task-same-trace"),
    ]
    for action, resource_type, resource_id in audit_resources:
        await database.execute(
            """
            INSERT INTO audit_logs (
                venue_id, user_id, action, resource_type, resource_id,
                outcome, trace_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'SUCCEEDED', ?, '{}', ?)
            """,
            (
                "venue-alpha",
                admin["id"],
                action,
                resource_type,
                resource_id,
                original_trace_id,
                expired_at,
            ),
        )
    activity_keys = [
        f"task-created:{orphan.id}",
        f"task-created:{missing_task_id}",
        f"task-decomposed:{decomposition_id}",
    ]
    for index, idempotency_key in enumerate(activity_keys):
        await database.execute(
            """
            INSERT INTO event_activities (
                id, venue_id, event_id, session_id, trace_id, activity_type,
                payload_json, idempotency_key, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?, ?)
            """,
            (
                f"activity-partial-cleanup-{index}",
                "venue-alpha",
                "event-partial-status-cleanup",
                "session-partial-status-cleanup",
                original_trace_id,
                "TASK_DECOMPOSED" if index == 2 else "TASK_CREATED",
                idempotency_key,
                admin["id"],
                expired_at,
            ),
        )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.get(
            "/admin/tasks/decompositions/status",
            headers=admin_headers,
            params={"idempotency_key": "partial-status-cleanup-001"},
        )

    try:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "FAILED"
        assert response.json()["trace_id"] == original_trace_id
        assert await database.fetch_one(
            """
            SELECT id FROM audit_logs
            WHERE venue_id = ? AND resource_id = ?
            """,
            ("venue-alpha", "unrelated-task-same-trace"),
        ) is not None
        for resource_id in (orphan.id, missing_task_id, decomposition_id):
            assert await database.fetch_one(
                "SELECT id FROM audit_logs WHERE venue_id = ? AND resource_id = ?",
                ("venue-alpha", resource_id),
            ) is None
        for idempotency_key in activity_keys:
            assert await database.fetch_one(
                """
                SELECT id FROM event_activities
                WHERE venue_id = ? AND idempotency_key = ?
                """,
                ("venue-alpha", idempotency_key),
            ) is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_decompose_tasks_rejects_invalid_model_contract_without_partial_writes(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.skills.todo.skill.llm_client",
        TodoLLMStub(
            {
                "tasks": [
                    {"description": "有效任务", "depends_on": []},
                    {"description": "非法依赖任务", "depends_on": [7]},
                ]
            }
        ),
    )
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-todo-invalid-output",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "todo-invalid-output-001"},
            json={
                "goal": "生成不应部分落库的任务",
                "session_id": "session-todo-invalid-output",
            },
        )

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "TASK_DECOMPOSITION_FAILED"
    assert detail["retryable"] is True
    task_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM tasks WHERE session_id = ?",
        ("session-todo-invalid-output",),
    )
    assert task_count["total"] == 0
    audit_row = await database.fetch_one(
        """
        SELECT action, outcome, trace_id FROM audit_logs
        WHERE action = 'TASK_DECOMPOSITION_FAILED' AND resource_id = ?
        """,
        ("session-todo-invalid-output",),
    )
    assert audit_row["outcome"] == "FAILED"
    assert audit_row["trace_id"] == detail["trace_id"]
    await database.close()


@pytest.mark.asyncio
async def test_decompose_tasks_rejects_cross_tenant_session_and_assignee(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.skills.todo.skill.llm_client",
        TodoLLMStub({"tasks": [{"description": "租户内任务", "depends_on": []}]}),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        venue = await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-beta", "name": "南麓景区"},
        )
        assert venue.status_code == 201, venue.text
        beta_user = await create_user(
            client,
            admin_headers,
            username="todo-beta-user",
            role="operator",
            venue_id="venue-beta",
        )
        alpha_admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
        await insert_session(
            database,
            session_id="session-todo-alpha",
            user_id=alpha_admin["id"],
            venue_id="venue-alpha",
        )
        await insert_session(
            database,
            session_id="session-todo-beta",
            user_id=beta_user["id"],
            venue_id="venue-beta",
        )

        cross_session = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "X-Trace-ID": "trace-cross-session", "Idempotency-Key": "todo-cross-session-001"},
            json={"goal": "越权会话", "session_id": "session-todo-beta"},
        )
        cross_assignee = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "X-Trace-ID": "trace-cross-assignee", "Idempotency-Key": "todo-cross-assignee-001"},
            json={
                "goal": "越权负责人",
                "session_id": "session-todo-alpha",
                "assigned_user_id": beta_user["id"],
            },
        )

    assert cross_session.status_code == 404
    assert cross_session.json()["detail"]["code"] == "SESSION_NOT_FOUND"
    assert cross_assignee.status_code == 400
    assert cross_assignee.json()["detail"]["code"] == "TASK_ASSIGNEE_INVALID"
    assert await database.fetch_one(
        "SELECT id FROM tasks WHERE venue_id = ? AND session_id IN (?, ?)",
        ("venue-alpha", "session-todo-alpha", "session-todo-beta"),
    ) is None
    await database.close()


@pytest.mark.asyncio
async def test_decompose_tasks_audits_task_graph_unavailable(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-todo-graph-unavailable",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    app.state.task_graph = None
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "todo-graph-unavailable-001"},
            json={
                "goal": "验证任务服务不可用审计",
                "session_id": "session-todo-graph-unavailable",
            },
        )

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "TASK_GRAPH_NOT_READY"
    audit_row = await database.fetch_one(
        """
        SELECT action, outcome, trace_id, metadata_json FROM audit_logs
        WHERE action = 'TASK_DECOMPOSITION_FAILED' AND resource_id = ?
        """,
        ("session-todo-graph-unavailable",),
    )
    assert audit_row["outcome"] == "FAILED"
    assert audit_row["trace_id"] == detail["trace_id"]
    assert json.loads(audit_row["metadata_json"])["reason"] == "task_graph_not_ready"
    await database.close()


@pytest.mark.asyncio
async def test_decompose_tasks_rolls_back_when_task_persistence_fails(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.skills.todo.skill.llm_client",
        TodoLLMStub(
            {
                "tasks": [
                    {"description": "先成功写入的任务", "depends_on": []},
                    {"description": "触发持久化失败的任务", "depends_on": [0]},
                ]
            }
        ),
    )
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-todo-task-rollback",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        original_execute = database.execute
        task_insert_count = 0

        async def fail_second_task_insert(sql, parameters=()):
            nonlocal task_insert_count
            if "INSERT INTO tasks" in sql:
                task_insert_count += 1
                if task_insert_count == 2:
                    raise RuntimeError("injected task persistence failure")
            return await original_execute(sql, parameters)

        monkeypatch.setattr(database, "execute", fail_second_task_insert)
        response = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "todo-persistence-failure-001"},
            json={
                "goal": "验证任务持久化失败补偿",
                "session_id": "session-todo-task-rollback",
            },
        )

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "TASK_DECOMPOSITION_FAILED"
    task_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM tasks WHERE session_id = ?",
        ("session-todo-task-rollback",),
    )
    assert task_count["total"] == 0
    assert await app.state.task_graph.get_session_tasks("session-todo-task-rollback") == []
    await database.close()


@pytest.mark.asyncio
async def test_decompose_tasks_rolls_back_when_success_audit_fails(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.skills.todo.skill.llm_client",
        TodoLLMStub(
            {
                "tasks": [
                    {"description": "第一项审计任务", "depends_on": []},
                    {"description": "第二项审计任务", "depends_on": [0]},
                ]
            }
        ),
    )
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-todo-audit-rollback",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        original_execute = database.execute
        created_audit_count = 0

        async def fail_second_created_audit(sql, parameters=()):
            nonlocal created_audit_count
            if "INSERT INTO audit_logs" in sql and len(parameters) > 2 and parameters[2] == "TASK_CREATED":
                created_audit_count += 1
                if created_audit_count == 2:
                    raise RuntimeError("injected audit persistence failure")
            return await original_execute(sql, parameters)

        monkeypatch.setattr(database, "execute", fail_second_created_audit)
        response = await client.post(
            "/admin/tasks/decompose",
            headers={**admin_headers, "Idempotency-Key": "todo-audit-failure-001"},
            json={
                "goal": "验证审计失败补偿",
                "session_id": "session-todo-audit-rollback",
            },
        )

    assert response.status_code == 500, response.text
    assert response.json()["detail"]["code"] == "TASK_DECOMPOSITION_PERSISTENCE_FAILED"
    task_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM tasks WHERE session_id = ?",
        ("session-todo-audit-rollback",),
    )
    assert task_count["total"] == 0
    audit_rows = await database.fetch_all(
        "SELECT action, outcome FROM audit_logs WHERE resource_id = ? ORDER BY id",
        ("session-todo-audit-rollback",),
    )
    assert audit_rows == [{"action": "TASK_DECOMPOSITION_FAILED", "outcome": "FAILED"}]
    await database.close()


@pytest.mark.asyncio
async def test_staged_task_batch_is_hidden_until_atomic_activation(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    staged = await app.state.task_graph.create_task(
        "session-todo-staged",
        "暂存任务",
        venue_id="venue-alpha",
        defer_activation=True,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        hidden_list = await client.get("/admin/tasks", headers=admin_headers)
        hidden_detail = await client.get(f"/admin/tasks/{staged.id}", headers=admin_headers)
        hidden_start = await client.post(f"/admin/tasks/{staged.id}/start", headers=admin_headers)
        assert hidden_list.status_code == 200
        assert staged.id not in {task["id"] for task in hidden_list.json()["tasks"]}
        assert hidden_detail.status_code == 404
        assert hidden_start.status_code == 404

        activated = await app.state.task_graph.activate_tasks([staged.id])
        visible_list = await client.get("/admin/tasks", headers=admin_headers)

    assert activated[0].status == TaskStatus.PENDING
    assert staged.id in {task["id"] for task in visible_list.json()["tasks"]}
    await database.close()


@pytest.mark.asyncio
async def test_task_graph_waits_for_every_dependency_before_unblocking():
    graph = TaskGraph()
    first = await graph.create_task("session-multi-dependency", "完成设备检查")
    second = await graph.create_task("session-multi-dependency", "完成客流检查")
    dependent = await graph.create_task(
        "session-multi-dependency",
        "汇总联合检查结果",
        dependencies=[first.id, second.id],
    )

    assert dependent.status == TaskStatus.BLOCKED
    await graph.complete_task(first.id)
    assert dependent.status == TaskStatus.BLOCKED
    await graph.complete_task(second.id)
    assert dependent.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_complete_task_and_dependency_release_survive_restart_as_one_change(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    graph = app.state.task_graph
    prerequisite = await graph.create_task(
        "session-completion-recovery",
        "完成前置检查",
        venue_id="venue-alpha",
    )
    dependent = await graph.create_task(
        "session-completion-recovery",
        "汇总检查结果",
        dependencies=[prerequisite.id],
        venue_id="venue-alpha",
    )
    await graph.start_task(prerequisite.id)
    completed = await graph.complete_task(prerequisite.id, result={"verified": True})

    restarted_graph = TaskGraph(database)
    await restarted_graph.reload_from_db()
    recovered_prerequisite = await restarted_graph.get_task(prerequisite.id)
    recovered_dependent = await restarted_graph.get_task(dependent.id)
    runnable = await restarted_graph.get_runnable_tasks("session-completion-recovery")

    assert completed.status == TaskStatus.DONE
    assert recovered_prerequisite.status == TaskStatus.DONE
    assert recovered_dependent.status == TaskStatus.PENDING
    assert [task.id for task in runnable] == [dependent.id]
    await database.close()


@pytest.mark.asyncio
async def test_complete_task_atomic_write_failure_keeps_memory_and_database_unchanged(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    graph = app.state.task_graph
    prerequisite = await graph.create_task(
        "session-completion-atomic-failure",
        "完成前置检查",
        venue_id="venue-alpha",
    )
    dependent = await graph.create_task(
        "session-completion-atomic-failure",
        "汇总检查结果",
        dependencies=[prerequisite.id],
        venue_id="venue-alpha",
    )
    await graph.start_task(prerequisite.id)
    original_execute = database.execute

    async def fail_atomic_completion(sql, parameters=()):
        if "UPDATE tasks" in sql and "completed_at = CASE" in sql:
            raise RuntimeError("injected atomic completion failure")
        return await original_execute(sql, parameters)

    monkeypatch.setattr(database, "execute", fail_atomic_completion)
    with pytest.raises(RuntimeError, match="atomic completion failure"):
        await graph.complete_task(prerequisite.id, result={"verified": True})

    assert prerequisite.status == TaskStatus.RUNNING
    assert prerequisite.result is None
    assert dependent.status == TaskStatus.BLOCKED
    persisted_prerequisite = await database.fetch_one(
        "SELECT status, result FROM tasks WHERE id = ?",
        (prerequisite.id,),
    )
    persisted_dependent = await database.fetch_one(
        "SELECT status FROM tasks WHERE id = ?",
        (dependent.id,),
    )
    assert persisted_prerequisite == {"status": "RUNNING", "result": None}
    assert persisted_dependent["status"] == "BLOCKED"
    await database.close()


@pytest.mark.asyncio
async def test_reload_repairs_legacy_blocked_task_after_dependencies_are_done(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    graph = app.state.task_graph
    prerequisite = await graph.create_task(
        "session-legacy-dependency-recovery",
        "历史前置任务",
        venue_id="venue-alpha",
    )
    dependent = await graph.create_task(
        "session-legacy-dependency-recovery",
        "历史后继任务",
        dependencies=[prerequisite.id],
        venue_id="venue-alpha",
    )
    await database.execute(
        "UPDATE tasks SET status = 'DONE' WHERE id = ?",
        (prerequisite.id,),
    )

    restarted_graph = TaskGraph(database)
    await restarted_graph.reload_from_db()
    recovered_dependent = await restarted_graph.get_task(dependent.id)
    persisted_dependent = await database.fetch_one(
        "SELECT status FROM tasks WHERE id = ?",
        (dependent.id,),
    )

    assert recovered_dependent.status == TaskStatus.PENDING
    assert persisted_dependent["status"] == TaskStatus.PENDING.value
    await database.close()


@pytest.mark.asyncio
async def test_restart_finishes_prepared_decomposition_after_activation_crash(
    tmp_path,
    monkeypatch,
):
    class SimulatedProcessCrash(BaseException):
        pass

    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.skills.todo.skill.llm_client",
        TodoLLMStub(
            {
                "tasks": [
                    {"description": "恢复前置任务", "depends_on": []},
                    {"description": "恢复后继任务", "depends_on": [0]},
                ]
            }
        ),
    )
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-staged-crash-recovery",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )

    async def crash_during_activation(task_ids):
        raise SimulatedProcessCrash("process stopped before activation response")

    monkeypatch.setattr(app.state.task_graph, "activate_tasks", crash_during_activation)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        with pytest.raises(SimulatedProcessCrash):
            await client.post(
                "/admin/tasks/decompose",
                headers={**admin_headers, "Idempotency-Key": "decompose-crash-recovery-001"},
                json={
                    "goal": "验证暂存任务重启恢复",
                    "session_id": "session-staged-crash-recovery",
                },
            )

    restarted_graph = TaskGraph(database)
    await restarted_graph.reload_from_db()
    decomposition = await database.fetch_one(
        """
        SELECT * FROM task_decompositions
        WHERE venue_id = ? AND requested_by = ? AND idempotency_key = ?
        """,
        ("venue-alpha", admin["id"], "decompose-crash-recovery-001"),
    )
    task_ids = json.loads(decomposition["task_ids"])
    recovered_tasks = [await restarted_graph.get_task(task_id) for task_id in task_ids]
    original_result = json.loads(decomposition["response_json"])

    assert decomposition["status"] == "COMPLETED"
    assert [task.status for task in recovered_tasks] == [
        TaskStatus.PENDING,
        TaskStatus.BLOCKED,
    ]
    assert original_result["idempotency_key"] == "decompose-crash-recovery-001"
    assert [task["id"] for task in original_result["tasks"]] == task_ids
    await database.close()


@pytest.mark.asyncio
async def test_restart_expires_processing_decomposition_and_removes_orphans(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    admin = await database.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))
    await insert_session(
        database,
        session_id="session-processing-restart",
        user_id=admin["id"],
        venue_id="venue-alpha",
    )
    decomposition_id = "decomposition-processing-restart"
    orphan = await app.state.task_graph.create_task(
        "session-processing-restart",
        "重启后应清理的暂存任务",
        venue_id="venue-alpha",
        defer_activation=True,
        decomposition_id=decomposition_id,
    )
    now = time.time()
    await database.execute(
        """
        INSERT INTO task_decompositions (
            decomposition_id, venue_id, requested_by, idempotency_key,
            request_fingerprint, session_id, trace_id, status, task_ids,
            response_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?, NULL, NULL, ?, ?)
        """,
        (
            decomposition_id,
            "venue-alpha",
            admin["id"],
            "todo-processing-restart-001",
            "unused-restart-fingerprint",
            "session-processing-restart",
            "trace-processing-before-restart",
            json.dumps([orphan.id]),
            now,
            now,
        ),
    )

    restarted_graph = TaskGraph(database)
    await restarted_graph.reload_from_db()
    decomposition = await database.fetch_one(
        "SELECT status, error FROM task_decompositions WHERE decomposition_id = ?",
        (decomposition_id,),
    )
    orphan_row = await database.fetch_one("SELECT id FROM tasks WHERE id = ?", (orphan.id,))

    assert decomposition == {
        "status": "FAILED",
        "error": "processing_interrupted_by_restart",
    }
    assert orphan_row is None
    assert await restarted_graph.get_task(orphan.id) is None
    await database.close()


@pytest.mark.asyncio
async def test_restart_cleanup_preserves_trace_and_other_tenant_audits(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    admin = await database.fetch_one(
        "SELECT id FROM users WHERE username = ?",
        ("mvp-admin",),
    )
    decomposition_id = "decomposition-tenant-safe-restart"
    original_trace_id = "shared-client-trace-for-restart"
    orphan = await app.state.task_graph.create_task(
        "session-tenant-safe-restart",
        "仅清理当前场地的暂存任务",
        venue_id="venue-alpha",
        defer_activation=True,
        decomposition_id=decomposition_id,
    )
    now = time.time()
    await database.execute(
        """
        INSERT INTO task_decompositions (
            decomposition_id, venue_id, requested_by, idempotency_key,
            request_fingerprint, session_id, trace_id, status, task_ids,
            response_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?, NULL, NULL, ?, ?)
        """,
        (
            decomposition_id,
            "venue-alpha",
            admin["id"],
            "tenant-safe-restart-001",
            "unused-tenant-safe-fingerprint",
            "session-tenant-safe-restart",
            original_trace_id,
            json.dumps([orphan.id]),
            now,
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO audit_logs (
            venue_id, user_id, action, resource_type, resource_id,
            outcome, trace_id, metadata_json, created_at
        ) VALUES (?, ?, ?, 'task', ?, 'SUCCEEDED', ?, '{}', ?)
        """,
        ("venue-alpha", admin["id"], "TASK_CREATED", orphan.id, original_trace_id, now),
    )
    await database.execute(
        """
        INSERT INTO audit_logs (
            venue_id, user_id, action, resource_type, resource_id,
            outcome, trace_id, metadata_json, created_at
        ) VALUES (?, ?, ?, 'task', ?, 'SUCCEEDED', ?, '{}', ?)
        """,
        (
            "venue-other",
            "other-tenant-user",
            "TASK_CREATED",
            "other-tenant-task",
            original_trace_id,
            now,
        ),
    )

    restarted_graph = TaskGraph(database)
    await restarted_graph.reload_from_db()

    try:
        decomposition = await database.fetch_one(
            """
            SELECT status, error, trace_id FROM task_decompositions
            WHERE decomposition_id = ?
            """,
            (decomposition_id,),
        )
        assert decomposition == {
            "status": "FAILED",
            "error": "processing_interrupted_by_restart",
            "trace_id": original_trace_id,
        }
        assert await database.fetch_one(
            """
            SELECT id FROM audit_logs
            WHERE venue_id = ? AND action = 'TASK_CREATED' AND resource_id = ?
            """,
            ("venue-alpha", orphan.id),
        ) is None
        assert await database.fetch_one(
            """
            SELECT id FROM audit_logs
            WHERE venue_id = ? AND action = 'TASK_CREATED' AND resource_id = ?
            """,
            ("venue-other", "other-tenant-task"),
        ) is not None
    finally:
        await database.close()
