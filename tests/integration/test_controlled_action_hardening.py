import asyncio
import json
import time

import aiosqlite
import httpx
import pytest

from src.memory_palace.core.permissions import (
    PermissionEngine,
    SensitivityLevel,
    get_permission_engine,
)
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.tools import tool_executor
from tests.integration.test_mvp_business_apis import build_app, login


async def _disable_notifications(engine: PermissionEngine) -> None:
    async def no_notification(_approval):
        return None

    engine._notify_admin = no_notification


async def _request(
    engine: PermissionEngine,
    tool_name: str,
    *,
    venue_id: str = "venue-alpha",
    correlation_trace_id: str = "trace-request-1",
) -> str:
    response = await engine.check_and_execute(
        tool_name,
        {"message": "东门客流达到预警阈值", "level": "warning"},
        {
            "session_id": "session-1",
            "user_id": "operator-1",
            "agent_name": "commander",
            "venue_id": venue_id,
            "correlation_trace_id": correlation_trace_id,
        },
    )
    assert response["status"] == "pending_approval"
    return response["approval_id"]


async def _insert_formal_action_context(
    database,
    *,
    user_id: str,
    venue_id: str = "venue-alpha",
    session_id: str = "session-event-action",
    event_id: str = "event-action-001",
    task_id: str = "task-action-001",
    event_business_id: str = "SJ-20260730-ACTION01",
    task_business_id: str = "RW-20260730-ACTION01",
) -> None:
    now = time.time()
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, stage, created_at, updated_at
        ) VALUES (?, ?, ?, 'active', ?, ?)
        """,
        (session_id, user_id, venue_id, now, now),
    )
    await database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, push_id, from_user, raw_text, event_type,
            severity, context_trigger_data, memory_content, created_at,
            confirmed_at, venue_id, source_type, status, trace_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, 'LIVE', 'OPEN', ?, ?)
        """,
        (
            event_id,
            event_business_id,
            "message-action-001",
            user_id,
            "12 号车右后轮异响，需要停运并启用备用车。",
            "设备异常",
            "P1",
            "12 号车右后轮异响事件",
            now,
            now,
            venue_id,
            "trace-event-action",
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO tasks (
            id, business_id, venue_id, session_id, event_id, description,
            status, dependencies, result_schema_json, evidence_refs_json,
            result, assigned_user_id, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'DONE', '[]', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            task_business_id,
            venue_id,
            session_id,
            event_id,
            "完成空载低速三轮试车并记录温度和异响",
            json.dumps(
                {
                    "type": "object",
                    "required": ["rounds", "temperature_c", "abnormal_noise"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                [
                    {
                        "type": "photo",
                        "name": "空载试车记录.jpg",
                        "asset_id": "asset-action-001",
                    }
                ],
                ensure_ascii=False,
            ),
            json.dumps(
                {"rounds": 3, "temperature_c": 33.2, "abnormal_noise": False},
                ensure_ascii=False,
            ),
            user_id,
            now - 300,
            now,
            now,
        ),
    )


async def _insert_simulator_recipient(
    database,
    *,
    user_id: str,
    display_name: str,
    job_title: str,
    session_id: str,
    updated_at: float,
    venue_id: str = "venue-alpha",
) -> None:
    await database.execute(
        """
        INSERT INTO users (
            id, username, password_hash, display_name, role, venue_id,
            department, job_title, status, created_at, updated_at
        ) VALUES (?, ?, 'test-password-hash', ?, 'operator', ?,
                  '现场运营部', ?, 'ACTIVE', ?, ?)
        """,
        (
            user_id,
            user_id,
            display_name,
            venue_id,
            job_title,
            updated_at,
            updated_at,
        ),
    )
    await database.execute(
        """
        INSERT INTO channel_identities (
            id, venue_id, channel, external_tenant_id, external_user_id,
            user_id, status, created_at, updated_at
        ) VALUES (?, ?, 'WECOM_SIMULATOR', ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            f"identity-{user_id}",
            venue_id,
            f"corp-{venue_id}",
            f"wecom-{user_id}",
            user_id,
            updated_at,
            updated_at,
        ),
    )
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, stage, created_at, updated_at
        ) VALUES (?, ?, ?, 'active', ?, ?)
        """,
        (session_id, user_id, venue_id, updated_at, updated_at),
    )
    await database.execute(
        """
        INSERT INTO channel_conversations (
            session_id, venue_id, channel, external_conversation_id,
            user_id, status, created_at, updated_at
        ) VALUES (?, ?, 'WECOM_SIMULATOR', ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            session_id,
            venue_id,
            f"conversation-{session_id}",
            user_id,
            updated_at,
            updated_at,
        ),
    )


@pytest.mark.asyncio
async def test_formal_event_action_persists_relationships_and_task_evidence(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    notifications = []

    async def record_notification(approval):
        notifications.append(approval.approval_id)

    monkeypatch.setattr(engine, "_notify_admin", record_notification)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        response = await client.post(
            "/admin/action-requests",
            headers={**admin_headers, "Idempotency-Key": "event-action-request-001"},
            json={
                "tool_name": "send_in_app_alert",
                "session_id": "session-event-action",
                "event_id": "event-action-001",
                "task_id": "task-action-001",
                "message": "12 号车今晚继续停运，启用 7 号备用车。",
                "priority": "warning",
            },
        )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["business_id"].startswith("SP-")
    assert payload["event_id"] == "event-action-001"
    assert payload["task_id"] == "task-action-001"

    approval = await database.fetch_one(
        "SELECT * FROM approval_requests WHERE approval_id = ?",
        (payload["approval_id"],),
    )
    evidence = json.loads(approval["evidence_snapshot_json"])
    assert approval["business_id"] == payload["business_id"]
    assert approval["event_id"] == "event-action-001"
    assert approval["task_id"] == "task-action-001"
    assert approval["idempotency_key"] == "event-action-request-001"
    assert evidence["task"]["business_id"] == "RW-20260730-ACTION01"
    assert evidence["task"]["result"]["rounds"] == 3
    assert evidence["task"]["evidence_refs"][0]["asset_id"] == "asset-action-001"

    activity = await database.fetch_one(
        """
        SELECT * FROM event_activities
        WHERE event_id = ? AND activity_type = 'APPROVAL_REQUESTED'
        """,
        ("event-action-001",),
    )
    activity_payload = json.loads(activity["payload_json"])
    assert activity_payload["approval_business_id"] == payload["business_id"]
    assert activity_payload["task_business_id"] == "RW-20260730-ACTION01"
    assert notifications == [payload["approval_id"]]
    await database.close()


@pytest.mark.asyncio
async def test_formal_action_code_uses_authoritative_manager_decision_policy(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    await _disable_notifications(engine)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        response = await client.post(
            "/admin/action-requests",
            headers={**admin_headers, "Idempotency-Key": "suspend-vehicle-action-001"},
            json={
                "action_code": "SUSPEND_PASSENGER_VEHICLE",
                "session_id": "session-event-action",
                "event_id": "event-action-001",
                "task_id": "task-action-001",
                "message": "12 号车今晚继续停运观察。",
                "priority": "warning",
            },
        )

    assert response.status_code == 202, response.text
    approval = await database.fetch_one(
        "SELECT tool_name, args, evidence_snapshot_json FROM approval_requests WHERE approval_id = ?",
        (response.json()["approval_id"],),
    )
    assert approval["tool_name"] == "record_manager_decision"
    assert json.loads(approval["args"])["decision"] == "SUSPEND_PASSENGER_VEHICLE"
    evidence = json.loads(approval["evidence_snapshot_json"])
    assert evidence["action_code"] == "SUSPEND_PASSENGER_VEHICLE"
    await database.close()


@pytest.mark.asyncio
async def test_manager_decision_tool_requires_registered_action_code(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    await _disable_notifications(engine)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        response = await client.post(
            "/admin/action-requests",
            headers={**admin_headers, "Idempotency-Key": "manager-decision-without-code"},
            json={
                "tool_name": "record_manager_decision",
                "session_id": "session-event-action",
                "event_id": "event-action-001",
                "task_id": "task-action-001",
                "message": "继续停运并等待进一步检查。",
                "priority": "warning",
            },
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "ACTION_CODE_REQUIRED"
    approvals = await database.fetch_one(
        "SELECT COUNT(*) AS count FROM approval_requests WHERE venue_id = ?",
        ("venue-alpha",),
    )
    assert approvals["count"] == 0
    await database.close()


@pytest.mark.asyncio
async def test_event_participant_action_freezes_readable_simulator_targets(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    await _disable_notifications(engine)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        now = time.time()
        await _insert_simulator_recipient(
            database,
            user_id="reporter-1",
            display_name="李明",
            job_title="现场巡检员",
            session_id="sim-reporter-old",
            updated_at=now - 60,
        )
        await database.execute(
            "UPDATE channel_conversations SET status = 'INACTIVE' WHERE session_id = ?",
            ("sim-reporter-old",),
        )
        await database.execute(
            """
            INSERT INTO sessions (
                session_id, user_id, venue_id, stage, created_at, updated_at
            ) VALUES ('sim-reporter-new', 'reporter-1', 'venue-alpha',
                      'active', ?, ?)
            """,
            (now, now),
        )
        await database.execute(
            """
            INSERT INTO channel_conversations (
                session_id, venue_id, channel, external_conversation_id,
                user_id, status, created_at, updated_at
            ) VALUES ('sim-reporter-new', 'venue-alpha', 'WECOM_SIMULATOR',
                      'conversation-reporter-new', 'reporter-1', 'ACTIVE', ?, ?)
            """,
            (now, now),
        )
        await _insert_simulator_recipient(
            database,
            user_id="owner-1",
            display_name="陈雨",
            job_title="当日值班经理",
            session_id="sim-owner",
            updated_at=now - 20,
        )
        await _insert_simulator_recipient(
            database,
            user_id="worker-1",
            display_name="王芳",
            job_title="设备维修员",
            session_id="sim-worker",
            updated_at=now - 10,
        )
        await database.execute(
            """
            UPDATE confirmed_events
            SET from_user = 'reporter-1', assigned_to = 'owner-1'
            WHERE event_id = 'event-action-001'
            """
        )
        await database.execute(
            """
            UPDATE tasks SET assigned_user_id = 'worker-1'
            WHERE id = 'task-action-001'
            """
        )
        await database.execute(
            """
            INSERT INTO tasks (
                id, business_id, venue_id, session_id, event_id, description,
                status, dependencies, result_schema_json, evidence_refs_json,
                assigned_user_id, created_at, updated_at
            ) VALUES (
                'task-action-reporter', 'RW-20260731-REPORTER', 'venue-alpha',
                'session-event-action', 'event-action-001', '补充现场照片',
                'DONE', '[]', '{}', '[]', 'reporter-1', ?, ?
            )
            """,
            (now, now),
        )

        request_body = {
            "tool_name": "send_in_app_alert",
            "recipient_scope": "EVENT_PARTICIPANTS",
            "session_id": "session-event-action",
            "event_id": "event-action-001",
            "task_id": "task-action-001",
            "message": "扶梯区域已封控，请相关人员同步处置进展。",
            "priority": "warning",
        }
        request_headers = {
            **admin_headers,
            "Idempotency-Key": "event-participants-001",
        }
        response = await client.post(
            "/admin/action-requests",
            headers=request_headers,
            json=request_body,
        )
        await database.execute(
            "UPDATE channel_conversations SET status = 'INACTIVE' WHERE session_id = ?",
            ("sim-owner",),
        )
        replay = await client.post(
            "/admin/action-requests",
            headers=request_headers,
            json=request_body,
        )

    assert response.status_code == 202, response.text
    assert replay.status_code == 202, replay.text
    assert replay.json()["approval_id"] == response.json()["approval_id"]
    assert replay.json()["idempotent_replay"] is True
    approval = await database.fetch_one(
        "SELECT args, evidence_snapshot_json FROM approval_requests WHERE approval_id = ?",
        (response.json()["approval_id"],),
    )
    args = json.loads(approval["args"])
    evidence = json.loads(approval["evidence_snapshot_json"])
    assert args["recipient_scope"] == "EVENT_PARTICIPANTS"
    assert "targets" not in args
    assert evidence["delivery"]["scope"] == "EVENT_PARTICIPANTS"
    assert evidence["delivery"]["channel"] == "WECOM_SIMULATOR_OUTBOX"
    assert evidence["delivery"]["target_count"] == 3
    targets = {
        target["user_id"]: target
        for target in evidence["delivery"]["targets"]
    }
    assert targets["reporter-1"] == {
        "user_id": "reporter-1",
        "display_name": "李明",
        "department": "现场运营部",
        "job_title": "现场巡检员",
        "session_id": "sim-reporter-new",
        "source_roles": ["EVENT_REPORTER", "TASK_ASSIGNEE"],
    }
    assert targets["owner-1"]["display_name"] == "陈雨"
    assert targets["owner-1"]["source_roles"] == ["EVENT_OWNER"]
    assert targets["worker-1"]["display_name"] == "王芳"
    assert targets["worker-1"]["source_roles"] == ["TASK_ASSIGNEE"]
    await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("readiness_state", "expected_reason"),
    (
        ("missing_session", "SIMULATOR_SESSION_MISSING"),
        ("inactive_user", "USER_INACTIVE"),
    ),
)
async def test_event_participant_request_fails_without_creating_approval_when_recipient_is_not_ready(
    tmp_path,
    monkeypatch,
    readiness_state,
    expected_reason,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    await _disable_notifications(engine)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        now = time.time()
        await _insert_simulator_recipient(
            database,
            user_id="recipient-not-ready",
            display_name="赵敏",
            job_title="现场协调员",
            session_id="sim-not-ready",
            updated_at=now,
        )
        if readiness_state == "missing_session":
            await database.execute(
                "UPDATE channel_conversations SET status = 'INACTIVE' WHERE session_id = ?",
                ("sim-not-ready",),
            )
        else:
            await database.execute(
                "UPDATE users SET status = 'DISABLED' WHERE id = ?",
                ("recipient-not-ready",),
            )
        await database.execute(
            """
            UPDATE confirmed_events
            SET from_user = 'recipient-not-ready', assigned_to = NULL
            WHERE event_id = 'event-action-001'
            """
        )
        await database.execute(
            """
            UPDATE tasks SET assigned_user_id = 'recipient-not-ready'
            WHERE id = 'task-action-001'
            """
        )

        response = await client.post(
            "/admin/action-requests",
            headers={**admin_headers, "Idempotency-Key": f"not-ready-{readiness_state}"},
            json={
                "tool_name": "send_in_app_alert",
                "recipient_scope": "EVENT_PARTICIPANTS",
                "session_id": "session-event-action",
                "event_id": "event-action-001",
                "task_id": "task-action-001",
                "message": "请事件相关人员同步进展。",
                "priority": "warning",
            },
        )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "SIMULATOR_RECIPIENTS_NOT_READY"
    assert detail["missing_recipients"][0]["display_name"] == "赵敏"
    assert detail["missing_recipients"][0]["reason_code"] == expected_reason
    approval_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM approval_requests",
    )
    push_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM push_logs",
    )
    assert approval_count["total"] == 0
    assert push_count["total"] == 0
    await database.close()


@pytest.mark.asyncio
async def test_formal_event_action_rejects_cross_tenant_and_mismatched_context(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    await _disable_notifications(engine)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        await _insert_formal_action_context(
            database,
            user_id=admin["id"],
            session_id="session-event-other",
            event_id="event-action-other",
            task_id="task-action-other",
            event_business_id="SJ-20260730-ACTION02",
            task_business_id="RW-20260730-ACTION02",
        )
        venue = await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-beta", "name": "南麓游客中心"},
        )
        assert venue.status_code == 201, venue.text
        await _insert_formal_action_context(
            database,
            user_id=admin["id"],
            venue_id="venue-beta",
            session_id="session-event-beta",
            event_id="event-action-beta",
            task_id="task-action-beta",
            event_business_id="SJ-20260730-ACTION03",
            task_business_id="RW-20260730-ACTION03",
        )
        body = {
            "tool_name": "send_in_app_alert",
            "session_id": "session-event-action",
            "event_id": "event-action-001",
            "task_id": "task-action-001",
            "message": "12 号车今晚继续停运，启用 7 号备用车。",
            "priority": "warning",
        }
        foreign_event = await client.post(
            "/admin/action-requests",
            headers=admin_headers,
            json={
                **body,
                "event_id": "event-action-beta",
                "task_id": "task-action-beta",
            },
        )
        foreign_task = await client.post(
            "/admin/action-requests",
            headers=admin_headers,
            json={**body, "task_id": "task-action-beta"},
        )
        mismatched = await client.post(
            "/admin/action-requests",
            headers=admin_headers,
            json={**body, "task_id": "task-action-other"},
        )

    assert foreign_event.status_code == 404, foreign_event.text
    assert foreign_event.json()["detail"]["code"] == "EVENT_NOT_FOUND"
    assert foreign_task.status_code == 404, foreign_task.text
    assert foreign_task.json()["detail"]["code"] == "TASK_NOT_FOUND"
    assert mismatched.status_code == 409, mismatched.text
    assert mismatched.json()["detail"]["code"] == "ACTION_CONTEXT_MISMATCH"
    approval_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM approval_requests"
    )
    assert approval_count["total"] == 0
    await database.close()


@pytest.mark.asyncio
async def test_formal_event_action_idempotency_replays_same_request_and_rejects_conflict(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    notifications = []

    async def record_notification(approval):
        notifications.append(approval.approval_id)

    monkeypatch.setattr(engine, "_notify_admin", record_notification)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        headers = {**admin_headers, "Idempotency-Key": "event-action-idempotent-001"}
        body = {
            "tool_name": "send_in_app_alert",
            "session_id": "session-event-action",
            "event_id": "event-action-001",
            "task_id": "task-action-001",
            "message": "12 号车今晚继续停运，启用 7 号备用车。",
            "priority": "warning",
        }
        first = await client.post("/admin/action-requests", headers=headers, json=body)
        replay = await client.post("/admin/action-requests", headers=headers, json=body)
        conflict = await client.post(
            "/admin/action-requests",
            headers=headers,
            json={**body, "message": "改为启用 8 号备用车。"},
        )

    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert replay.json()["approval_id"] == first.json()["approval_id"]
    assert replay.json()["idempotent_replay"] is True
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "APPROVAL_IDEMPOTENCY_CONFLICT"

    approval_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM approval_requests WHERE idempotency_key = ?",
        ("event-action-idempotent-001",),
    )
    activity_count = await database.fetch_one(
        """
        SELECT COUNT(*) AS total FROM event_activities
        WHERE event_id = ? AND activity_type = 'APPROVAL_REQUESTED'
        """,
        ("event-action-001",),
    )
    assert approval_count["total"] == 1
    assert activity_count["total"] == 1
    assert notifications == [first.json()["approval_id"]]
    await database.close()


@pytest.mark.asyncio
async def test_rejected_action_resubmission_persists_link_and_decision_activities(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    notifications = []

    async def record_notification(approval):
        notifications.append(approval.approval_id)

    monkeypatch.setattr(engine, "_notify_admin", record_notification)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        admin = await database.fetch_one(
            "SELECT id FROM users WHERE username = ?",
            ("mvp-admin",),
        )
        await _insert_formal_action_context(database, user_id=admin["id"])
        body = {
            "tool_name": "send_in_app_alert",
            "session_id": "session-event-action",
            "event_id": "event-action-001",
            "task_id": "task-action-001",
            "message": "12 号车今晚继续停运，启用 7 号备用车。",
            "priority": "warning",
        }
        first = await client.post(
            "/admin/action-requests",
            headers={**admin_headers, "Idempotency-Key": "event-action-first-001"},
            json=body,
        )
        assert first.status_code == 202, first.text
        first_id = first.json()["approval_id"]
        rejected = await client.post(
            f"/admin/approvals/{first_id}/reject",
            headers=admin_headers,
            json={"comment": "缺少校正后的空载三轮试车记录。"},
        )
        assert rejected.status_code == 200, rejected.text

        resubmit_headers = {
            **admin_headers,
            "Idempotency-Key": "event-action-resubmit-001",
        }
        resubmit_body = {
            **body,
            "supersedes_approval_id": first_id,
            "message": "已补齐三轮试车记录；12 号车今晚继续停运，启用 7 号备用车。",
        }
        resubmitted = await client.post(
            "/admin/action-requests",
            headers=resubmit_headers,
            json=resubmit_body,
        )
        assert resubmitted.status_code == 202, resubmitted.text
        second_id = resubmitted.json()["approval_id"]
        replayed = await client.post(
            "/admin/action-requests",
            headers=resubmit_headers,
            json=resubmit_body,
        )
        assert replayed.status_code == 202, replayed.text
        assert replayed.json()["approval_id"] == second_id
        assert replayed.json()["supersedes_approval_id"] == first_id
        assert replayed.json()["idempotent_replay"] is True
        approved = await client.post(
            f"/admin/approvals/{second_id}/approve",
            headers=admin_headers,
            json={"comment": "同意停运观察并启用备用车。"},
        )

    assert approved.status_code == 200, approved.text
    second = await database.fetch_one(
        "SELECT * FROM approval_requests WHERE approval_id = ?",
        (second_id,),
    )
    assert second["supersedes_approval_id"] == first_id
    assert second["event_id"] == "event-action-001"
    assert second["task_id"] == "task-action-001"
    assert second["status"] == "APPROVED"
    assert second["execution_status"] == "SUCCEEDED"

    activities = await database.fetch_all(
        """
        SELECT activity_type, payload_json FROM event_activities
        WHERE event_id = ?
          AND activity_type IN (
              'APPROVAL_REQUESTED', 'APPROVAL_REJECTED',
              'APPROVAL_RESUBMITTED', 'APPROVAL_APPROVED'
          )
        ORDER BY created_at ASC
        """,
        ("event-action-001",),
    )
    assert [row["activity_type"] for row in activities] == [
        "APPROVAL_REQUESTED",
        "APPROVAL_REJECTED",
        "APPROVAL_RESUBMITTED",
        "APPROVAL_APPROVED",
    ]
    for row in activities:
        activity_payload = json.loads(row["payload_json"])
        assert activity_payload["approval_business_id"].startswith("SP-")
        assert activity_payload["task_business_id"] == "RW-20260730-ACTION01"
        assert activity_payload["task_title"] == "完成空载低速三轮试车并记录温度和异响"
    assert notifications == [first_id, second_id]
    await database.close()


@pytest.mark.asyncio
async def test_approval_trace_log_and_in_app_push_are_persistent_and_idempotent(
    tmp_path,
):
    database = AsyncDBClient(tmp_path / "controlled-action.db")
    await init_database(database)
    engine = PermissionEngine(database)
    await _disable_notifications(engine)

    approval_id = await _request(engine, "send_in_app_alert")
    approval = await engine.get_approval(approval_id)
    assert approval.to_dict()["correlation_trace_id"] == "trace-request-1"
    assert approval.execution_status == "NOT_STARTED"

    approved = await engine.approve(
        approval_id,
        reviewer="admin-1",
        venue_id="venue-alpha",
        trace_id="trace-execution-1",
    )
    assert approved is True

    approval_row = await database.fetch_one(
        "SELECT * FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    )
    assert approval_row["correlation_trace_id"] == "trace-request-1"
    assert approval_row["execution_trace_id"] == "trace-execution-1"
    assert approval_row["execution_status"] == "SUCCEEDED"

    invocation = await database.fetch_one(
        "SELECT * FROM tool_invocation_logs WHERE approval_id = ?",
        (approval_id,),
    )
    assert invocation["trace_id"] == "trace-execution-1"
    assert invocation["venue_id"] == "venue-alpha"

    first_push = await database.fetch_one(
        "SELECT * FROM push_logs WHERE idempotency_key = ?",
        (approval_id,),
    )
    assert first_push["trace_id"] == "trace-execution-1"

    duplicate = await tool_executor.execute_tool(
        "send_in_app_alert",
        {"message": "东门客流达到预警阈值", "level": "warning"},
        context={
            "approval_id": approval_id,
            "session_id": "session-1",
            "user_id": "operator-1",
            "venue_id": "venue-alpha",
            "trace_id": "trace-execution-1",
            "_database": database,
        },
    )
    push_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM push_logs WHERE idempotency_key = ?",
        (approval_id,),
    )
    assert duplicate["result"]["push_id"] == first_push["push_id"]
    assert push_count["total"] == 1
    await database.close()


@pytest.mark.asyncio
async def test_event_participant_approval_fans_out_once_per_frozen_recipient(
    tmp_path,
):
    database = AsyncDBClient(tmp_path / "controlled-action-fanout.db")
    await init_database(database)
    now = time.time()
    await database.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES ('venue-alpha', '云栖山景区', 'ACTIVE', ?, ?)
        """,
        (now, now),
    )
    targets = []
    for user_id, display_name, job_title, session_id in (
        ("reporter-1", "李明", "现场巡检员", "sim-reporter"),
        ("owner-1", "陈雨", "当日值班经理", "sim-owner"),
        ("worker-1", "王芳", "设备维修员", "sim-worker"),
    ):
        await _insert_simulator_recipient(
            database,
            user_id=user_id,
            display_name=display_name,
            job_title=job_title,
            session_id=session_id,
            updated_at=now,
        )
        targets.append(
            {
                "user_id": user_id,
                "display_name": display_name,
                "department": "现场运营部",
                "job_title": job_title,
                "session_id": session_id,
                "source_roles": ["TASK_ASSIGNEE"],
            }
        )

    engine = PermissionEngine(database)
    await _disable_notifications(engine)
    requested = await engine.check_and_execute(
        "send_in_app_alert",
        {
            "message": "扶梯区域已封控，请相关人员同步处置进展。",
            "level": "warning",
            "recipient_scope": "EVENT_PARTICIPANTS",
        },
        {
            "session_id": "source-session",
            "event_id": "event-fanout-1",
            "task_id": "task-fanout-1",
            "user_id": "manager-1",
            "agent_name": "formal-client:manager-1",
            "venue_id": "venue-alpha",
            "correlation_trace_id": "trace-fanout-request",
            "evidence_snapshot": {
                "delivery": {
                    "scope": "EVENT_PARTICIPANTS",
                    "channel": "WECOM_SIMULATOR_OUTBOX",
                    "target_count": 3,
                    "targets": targets,
                }
            },
        },
    )
    approval_id = requested["approval_id"]

    approved = await engine.approve(
        approval_id,
        reviewer="admin-1",
        venue_id="venue-alpha",
        trace_id="trace-fanout-execution",
    )
    assert approved is True
    approval = await database.fetch_one(
        "SELECT execution_result FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    )
    execution = json.loads(approval["execution_result"])
    assert execution["result"]["status"] == "DELIVERED"
    assert execution["result"]["channel"] == "WECOM_SIMULATOR_OUTBOX"
    assert execution["result"]["target_count"] == 3
    assert execution["result"]["delivered_count"] == 3

    pushes = await database.fetch_all(
        """
        SELECT msg_id, channel, recipient, idempotency_key
        FROM push_logs
        WHERE venue_id = ? AND msg_id = ?
        ORDER BY recipient
        """,
        ("venue-alpha", approval_id),
    )
    assert pushes == [
        {
            "msg_id": approval_id,
            "channel": "WECOM_SIMULATOR_OUTBOX",
            "recipient": "session:sim-owner",
            "idempotency_key": f"{approval_id}:recipient:owner-1",
        },
        {
            "msg_id": approval_id,
            "channel": "WECOM_SIMULATOR_OUTBOX",
            "recipient": "session:sim-reporter",
            "idempotency_key": f"{approval_id}:recipient:reporter-1",
        },
        {
            "msg_id": approval_id,
            "channel": "WECOM_SIMULATOR_OUTBOX",
            "recipient": "session:sim-worker",
            "idempotency_key": f"{approval_id}:recipient:worker-1",
        },
    ]

    replay = await tool_executor.execute_tool(
        "send_in_app_alert",
        {
            "message": "扶梯区域已封控，请相关人员同步处置进展。",
            "level": "warning",
            "recipient_scope": "EVENT_PARTICIPANTS",
        },
        context={
            "approval_id": approval_id,
            "session_id": "source-session",
            "user_id": "manager-1",
            "venue_id": "venue-alpha",
            "trace_id": "trace-fanout-execution",
            "evidence_snapshot": {
                "delivery": {
                    "scope": "EVENT_PARTICIPANTS",
                    "channel": "WECOM_SIMULATOR_OUTBOX",
                    "target_count": 3,
                    "targets": targets,
                }
            },
            "_database": database,
        },
    )
    push_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM push_logs WHERE venue_id = ? AND msg_id = ?",
        ("venue-alpha", approval_id),
    )
    assert replay["result"]["delivered_count"] == 3
    assert push_count["total"] == 3
    await database.close()


@pytest.mark.asyncio
async def test_event_participant_execution_revalidates_frozen_recipient_before_any_push(
    tmp_path,
):
    database = AsyncDBClient(tmp_path / "controlled-action-revalidate-fanout.db")
    await init_database(database)
    now = time.time()
    await database.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES ('venue-alpha', '云栖山景区', 'ACTIVE', ?, ?)
        """,
        (now, now),
    )
    await _insert_simulator_recipient(
        database,
        user_id="recipient-1",
        display_name="李明",
        job_title="现场巡检员",
        session_id="sim-recipient-1",
        updated_at=now,
    )
    target = {
        "user_id": "recipient-1",
        "display_name": "李明",
        "department": "现场运营部",
        "job_title": "现场巡检员",
        "session_id": "sim-recipient-1",
        "source_roles": ["EVENT_REPORTER"],
    }
    engine = PermissionEngine(database)
    await _disable_notifications(engine)
    requested = await engine.check_and_execute(
        "send_in_app_alert",
        {
            "message": "请同步现场处置进展。",
            "level": "warning",
            "recipient_scope": "EVENT_PARTICIPANTS",
        },
        {
            "session_id": "source-session",
            "event_id": "event-revalidate-1",
            "task_id": "task-revalidate-1",
            "user_id": "manager-1",
            "agent_name": "formal-client:manager-1",
            "venue_id": "venue-alpha",
            "correlation_trace_id": "trace-revalidate-request",
            "evidence_snapshot": {
                "delivery": {
                    "scope": "EVENT_PARTICIPANTS",
                    "channel": "WECOM_SIMULATOR_OUTBOX",
                    "target_count": 1,
                    "targets": [target],
                }
            },
        },
    )
    await database.execute(
        "UPDATE channel_identities SET status = 'DISABLED' WHERE user_id = ?",
        ("recipient-1",),
    )

    approved = await engine.approve(
        requested["approval_id"],
        reviewer="admin-1",
        venue_id="venue-alpha",
        trace_id="trace-revalidate-execution",
    )

    assert approved is True
    approval = await database.fetch_one(
        "SELECT execution_status, execution_result FROM approval_requests WHERE approval_id = ?",
        (requested["approval_id"],),
    )
    execution = json.loads(approval["execution_result"])
    assert approval["execution_status"] == "FAILED"
    assert execution["status"] == "error"
    assert execution["code"] == "SIMULATOR_RECIPIENTS_NOT_READY"
    push_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM push_logs",
    )
    assert push_count["total"] == 0
    await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence_snapshot",
    (
        {},
        {
            "delivery": {
                "scope": "EVENT_PARTICIPANTS",
                "channel": "WECOM_SIMULATOR_OUTBOX",
                "targets": [],
            }
        },
        {
            "delivery": {
                "scope": "EVENT_PARTICIPANTS",
                "channel": "WECOM_SIMULATOR_OUTBOX",
                "targets": [{}],
            }
        },
    ),
    ids=("missing", "empty", "malformed"),
)
async def test_event_participant_execution_never_falls_back_without_frozen_targets(
    tmp_path,
    evidence_snapshot,
):
    database = AsyncDBClient(tmp_path / "controlled-action-invalid-fanout.db")
    await init_database(database)

    result = await tool_executor.execute_tool(
        "send_in_app_alert",
        {
            "message": "不得回退到单会话通知。",
            "level": "warning",
            "recipient_scope": "EVENT_PARTICIPANTS",
        },
        context={
            "approval_id": "approval-invalid-fanout",
            "session_id": "legacy-source-session",
            "user_id": "manager-1",
            "venue_id": "venue-alpha",
            "trace_id": "trace-invalid-fanout",
            "evidence_snapshot": evidence_snapshot,
            "_database": database,
        },
    )

    assert result["status"] == "error"
    assert result["code"] == "SIMULATOR_RECIPIENTS_NOT_READY"
    push_count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM push_logs",
    )
    assert push_count["total"] == 0
    await database.close()


@pytest.mark.asyncio
async def test_database_claim_allows_only_one_approval_executor(tmp_path, monkeypatch):
    database_path = tmp_path / "atomic-approval.db"
    primary = AsyncDBClient(database_path)
    secondary = AsyncDBClient(database_path)
    await init_database(primary)
    first_engine = PermissionEngine(primary)
    second_engine = PermissionEngine(secondary)
    await _disable_notifications(first_engine)
    await _disable_notifications(second_engine)

    execution_count = 0

    async def controlled_tool(message, level="warning"):
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.05)
        return {"delivered": True}

    monkeypatch.setitem(tool_executor._tools, "atomic_controlled_tool", controlled_tool)
    for engine in (first_engine, second_engine):
        engine.register_tool(
            "atomic_controlled_tool",
            SensitivityLevel.APPROVAL,
            cooldown_seconds=0,
        )

    approval_id = await _request(first_engine, "atomic_controlled_tool")
    await second_engine.reload_from_db()
    results = await asyncio.gather(
        first_engine.approve(
            approval_id,
            reviewer="admin-1",
            venue_id="venue-alpha",
            trace_id="trace-execution-a",
        ),
        second_engine.approve(
            approval_id,
            reviewer="admin-2",
            venue_id="venue-alpha",
            trace_id="trace-execution-b",
        ),
    )

    row = await primary.fetch_one(
        "SELECT execution_status FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    )
    assert sorted(results) == [False, True]
    assert execution_count == 1
    assert row["execution_status"] == "SUCCEEDED"
    await primary.close()
    await secondary.close()


@pytest.mark.asyncio
async def test_logging_failure_finishes_approval_as_failed(tmp_path, monkeypatch):
    database = AsyncDBClient(tmp_path / "logging-failure.db")
    await init_database(database)
    engine = PermissionEngine(database)
    await _disable_notifications(engine)
    engine.register_tool("logging_failure_tool", SensitivityLevel.APPROVAL)

    async def fail_logging(*_args, **_kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(engine, "_log_invocation", fail_logging)
    approval_id = await _request(engine, "logging_failure_tool")
    assert await engine.approve(
        approval_id,
        reviewer="admin-1",
        venue_id="venue-alpha",
        trace_id="trace-log-failure",
    )

    row = await database.fetch_one(
        "SELECT execution_status, execution_result, execution_error FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    )
    result = json.loads(row["execution_result"])
    assert row["execution_status"] == "FAILED"
    assert result["code"] == "INVOCATION_LOG_FAILED"
    assert "audit storage unavailable" in row["execution_error"]
    await database.close()


@pytest.mark.asyncio
async def test_tool_failure_finishes_approval_as_failed(tmp_path, monkeypatch):
    database = AsyncDBClient(tmp_path / "tool-failure.db")
    await init_database(database)
    engine = PermissionEngine(database)
    await _disable_notifications(engine)

    async def fail_tool(message, level="warning"):
        raise RuntimeError("provider rejected request")

    monkeypatch.setitem(tool_executor._tools, "failing_controlled_tool", fail_tool)
    engine.register_tool("failing_controlled_tool", SensitivityLevel.APPROVAL)
    approval_id = await _request(engine, "failing_controlled_tool")
    assert await engine.approve(
        approval_id,
        reviewer="admin-1",
        venue_id="venue-alpha",
        trace_id="trace-tool-failure",
    )

    row = await database.fetch_one(
        "SELECT execution_status, execution_error FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    )
    assert row["execution_status"] == "FAILED"
    assert "provider rejected request" in row["execution_error"]
    await database.close()


@pytest.mark.asyncio
async def test_approval_execution_outcomes_enter_event_timeline_once_per_tenant(
    tmp_path,
    monkeypatch,
):
    database = AsyncDBClient(tmp_path / "approval-event-timeline.db")
    await init_database(database)
    engine = PermissionEngine(database)
    await _disable_notifications(engine)

    async def delivered_tool(message, level="warning"):
        return {
            "status": "DELIVERED",
            "summary": "备用车辆调度通知已送达",
        }

    async def failed_tool(message, level="warning"):
        raise RuntimeError("provider rejected controlled action")

    log_failure_tool_calls = 0

    async def log_failure_tool(message, level="warning"):
        nonlocal log_failure_tool_calls
        log_failure_tool_calls += 1
        return {"status": "DELIVERED"}

    monkeypatch.setitem(tool_executor._tools, "timeline_delivered_tool", delivered_tool)
    monkeypatch.setitem(tool_executor._tools, "timeline_failed_tool", failed_tool)
    monkeypatch.setitem(tool_executor._tools, "timeline_log_failure_tool", log_failure_tool)
    for tool_name in (
        "timeline_delivered_tool",
        "timeline_failed_tool",
        "timeline_log_failure_tool",
    ):
        engine.register_tool(
            tool_name,
            SensitivityLevel.APPROVAL,
            cooldown_seconds=0,
        )

    original_log_invocation = engine._log_invocation

    async def selectively_fail_invocation_log(tool_name, args, context):
        if tool_name == "timeline_log_failure_tool":
            raise RuntimeError("invocation log storage unavailable")
        await original_log_invocation(tool_name, args, context)

    monkeypatch.setattr(engine, "_log_invocation", selectively_fail_invocation_log)

    cases = (
        {
            "name": "success",
            "tool_name": "timeline_delivered_tool",
            "venue_id": "venue-alpha",
            "event_id": "event-action-success",
            "event_business_id": "SJ-20260730-ACTION-SUCCESS",
            "task_id": "task-action-success",
            "task_business_id": "RW-20260730-ACTION-SUCCESS",
            "activity_type": "CONTROLLED_ACTION_EXECUTED",
            "execution_status": "SUCCEEDED",
            "summary": "受控动作执行成功：备用车辆调度通知已送达",
            "error": None,
        },
        {
            "name": "tool-failure",
            "tool_name": "timeline_failed_tool",
            "venue_id": "venue-beta",
            "event_id": "event-action-tool-failure",
            "event_business_id": "SJ-20260730-ACTION-TOOLFAIL",
            "task_id": "task-action-tool-failure",
            "task_business_id": "RW-20260730-ACTION-TOOLFAIL",
            "activity_type": "CONTROLLED_ACTION_FAILED",
            "execution_status": "FAILED",
            "summary": "受控动作执行失败：provider rejected controlled action",
            "error": "provider rejected controlled action",
        },
        {
            "name": "log-failure",
            "tool_name": "timeline_log_failure_tool",
            "venue_id": "venue-beta",
            "event_id": "event-action-log-failure",
            "event_business_id": "SJ-20260730-ACTION-LOGFAIL",
            "task_id": "task-action-log-failure",
            "task_business_id": "RW-20260730-ACTION-LOGFAIL",
            "activity_type": "CONTROLLED_ACTION_FAILED",
            "execution_status": "FAILED",
            "summary": "受控动作执行失败：invocation log storage unavailable",
            "error": "invocation log storage unavailable",
        },
    )
    requested = {}

    for case in cases:
        session_id = f"session-action-{case['name']}"
        await _insert_formal_action_context(
            database,
            user_id="operator-timeline",
            venue_id=case["venue_id"],
            session_id=session_id,
            event_id=case["event_id"],
            task_id=case["task_id"],
            event_business_id=case["event_business_id"],
            task_business_id=case["task_business_id"],
        )
        response = await engine.check_and_execute(
            case["tool_name"],
            {"message": "启用备用车辆并通知调度", "level": "warning"},
            {
                "session_id": session_id,
                "user_id": "operator-timeline",
                "agent_name": "commander",
                "venue_id": case["venue_id"],
                "event_id": case["event_id"],
                "task_id": case["task_id"],
                "correlation_trace_id": f"trace-request-{case['name']}",
                "evidence_snapshot": {
                    "event_business_id": case["event_business_id"],
                    "task": {
                        "business_id": case["task_business_id"],
                        "description": "完成空载低速三轮试车并记录温度和异响",
                    },
                },
            },
        )
        assert response["status"] == "pending_approval"
        requested[case["name"]] = response
        assert await engine.approve(
            response["approval_id"],
            reviewer=f"reviewer-{case['venue_id']}",
            venue_id=case["venue_id"],
            trace_id=f"trace-execution-{case['name']}",
        )
        assert not await engine.approve(
            response["approval_id"],
            reviewer=f"reviewer-{case['venue_id']}",
            venue_id=case["venue_id"],
            trace_id=f"trace-replay-{case['name']}",
        )

    activities = await database.fetch_all(
        """
        SELECT venue_id, event_id, trace_id, activity_type, payload_json,
               idempotency_key
        FROM event_activities
        WHERE activity_type IN (
            'CONTROLLED_ACTION_EXECUTED', 'CONTROLLED_ACTION_FAILED'
        )
        """
    )
    assert len(activities) == 3
    by_event_id = {row["event_id"]: row for row in activities}

    for case in cases:
        response = requested[case["name"]]
        activity = by_event_id[case["event_id"]]
        payload = json.loads(activity["payload_json"])
        assert activity["venue_id"] == case["venue_id"]
        assert activity["trace_id"] == f"trace-execution-{case['name']}"
        assert activity["activity_type"] == case["activity_type"]
        assert activity["idempotency_key"] == (
            f"approval:{response['approval_id']}:{case['activity_type'].lower()}"
        )
        assert payload["approval_business_id"] == response["business_id"]
        assert payload["task_business_id"] == case["task_business_id"]
        assert payload["execution_status"] == case["execution_status"]
        assert payload["summary"] == case["summary"]
        assert payload["execution_error"] == case["error"]

    assert log_failure_tool_calls == 0
    await database.close()


@pytest.mark.asyncio
async def test_cancelled_execution_is_finalized_before_cancellation_propagates(
    tmp_path,
    monkeypatch,
):
    database = AsyncDBClient(tmp_path / "cancelled-action.db")
    await init_database(database)
    engine = PermissionEngine(database)
    await _disable_notifications(engine)

    async def cancel_tool(message, level="warning"):
        raise asyncio.CancelledError

    monkeypatch.setitem(tool_executor._tools, "cancelled_controlled_tool", cancel_tool)
    engine.register_tool("cancelled_controlled_tool", SensitivityLevel.APPROVAL)
    approval_id = await _request(engine, "cancelled_controlled_tool")

    with pytest.raises(asyncio.CancelledError):
        await engine.approve(
            approval_id,
            reviewer="admin-1",
            venue_id="venue-alpha",
            trace_id="trace-cancelled",
        )

    row = await database.fetch_one(
        "SELECT execution_status, execution_error FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    )
    assert row["execution_status"] == "FAILED"
    assert "cancel" in row["execution_error"].lower()
    await database.close()


@pytest.mark.asyncio
async def test_reload_recovers_interrupted_and_legacy_approved_executions(tmp_path):
    database = AsyncDBClient(tmp_path / "approval-recovery.db")
    await init_database(database)
    now = 1_700_000_000.0
    for approval_id, status, execution_status, execution_result in (
        ("approval-interrupted", "APPROVED", "EXECUTING", None),
        ("approval-legacy-approved", "APPROVED", "NOT_STARTED", None),
        ("approval-complete", "APPROVED", "SUCCEEDED", '{"status":"executed"}'),
        ("approval-pending", "PENDING", "NOT_STARTED", None),
    ):
        await database.execute(
            """
            INSERT INTO approval_requests (
                approval_id, venue_id, tool_name, args, session_id, user_id,
                requested_at, requested_by, status, execution_status,
                execution_result, correlation_trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                "venue-alpha",
                "send_in_app_alert",
                "{}",
                "session-1",
                "operator-1",
                now,
                "commander",
                status,
                execution_status,
                execution_result,
                f"trace-{approval_id}",
            ),
        )

    engine = PermissionEngine(database)
    await engine.reload_from_db()

    rows = await database.fetch_all(
        "SELECT approval_id, execution_status, execution_error FROM approval_requests",
    )
    by_id = {row["approval_id"]: row for row in rows}
    assert by_id["approval-interrupted"]["execution_status"] == "FAILED"
    assert by_id["approval-legacy-approved"]["execution_status"] == "FAILED"
    assert by_id["approval-complete"]["execution_status"] == "SUCCEEDED"
    assert await engine.get_approval("approval-pending") is not None
    await database.close()


@pytest.mark.asyncio
async def test_rejected_approval_is_persisted_as_not_executed(tmp_path):
    database = AsyncDBClient(tmp_path / "rejected-action.db")
    await init_database(database)
    engine = PermissionEngine(database)
    await _disable_notifications(engine)
    engine.register_tool("rejected_controlled_tool", SensitivityLevel.APPROVAL)
    approval_id = await _request(engine, "rejected_controlled_tool")

    rejected = await engine.reject(
        approval_id,
        reviewer="admin-1",
        venue_id="venue-alpha",
    )
    row = await database.fetch_one(
        "SELECT status, execution_status FROM approval_requests WHERE approval_id = ?",
        (approval_id,),
    )

    assert rejected is True
    assert row["status"] == "REJECTED"
    assert row["execution_status"] == "NOT_EXECUTED"
    await database.close()


@pytest.mark.asyncio
async def test_cooldown_is_isolated_by_venue(monkeypatch):
    engine = PermissionEngine()
    execution_count = 0

    async def tenant_tool():
        nonlocal execution_count
        execution_count += 1
        return {"count": execution_count}

    monkeypatch.setitem(tool_executor._tools, "tenant_cooldown_tool", tenant_tool)
    engine.register_tool(
        "tenant_cooldown_tool",
        SensitivityLevel.FREE,
        cooldown_seconds=60,
    )

    first = await engine.check_and_execute(
        "tenant_cooldown_tool",
        {},
        {"venue_id": "venue-alpha"},
    )
    blocked = await engine.check_and_execute(
        "tenant_cooldown_tool",
        {},
        {"venue_id": "venue-alpha"},
    )
    other_tenant = await engine.check_and_execute(
        "tenant_cooldown_tool",
        {},
        {"venue_id": "venue-beta"},
    )

    assert first["status"] == "executed"
    assert blocked["status"] == "cooldown"
    assert other_tenant["status"] == "executed"
    assert execution_count == 2


@pytest.mark.asyncio
async def test_sqlite_and_postgres_schema_include_controlled_action_migrations(tmp_path):
    database_path = tmp_path / "legacy-schema.db"
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            """
            CREATE TABLE approval_requests (
                approval_id TEXT PRIMARY KEY, tool_name TEXT NOT NULL, args TEXT NOT NULL,
                session_id TEXT, user_id TEXT, requested_at REAL NOT NULL,
                requested_by TEXT, status TEXT DEFAULT 'PENDING', reviewed_at REAL,
                reviewed_by TEXT, comment TEXT, venue_id TEXT DEFAULT '',
                execution_result TEXT, execution_error TEXT
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE tool_invocation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tool_name TEXT NOT NULL,
                args TEXT NOT NULL, session_id TEXT, user_id TEXT, agent_name TEXT,
                logged_at REAL NOT NULL, venue_id TEXT DEFAULT ''
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE push_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, push_id TEXT UNIQUE NOT NULL,
                venue_id TEXT DEFAULT '', msg_id TEXT, from_user TEXT NOT NULL,
                raw_text TEXT NOT NULL, event_type TEXT, severity TEXT,
                stage1_triggered BOOLEAN, hit_keywords TEXT, stage2_triggered BOOLEAN,
                llm_confidence REAL, pushed_at REAL NOT NULL, confirmed_at REAL,
                adoption_status TEXT, confirmed_notes TEXT, confirmed_by TEXT,
                trace_id TEXT, channel TEXT DEFAULT 'legacy', recipient TEXT,
                delivery_status TEXT DEFAULT 'RECORDED', delivery_error TEXT
            )
            """
        )
        await connection.commit()

    sqlite_database = AsyncDBClient(database_path)
    await init_database(sqlite_database)
    expected_columns = {
        "approval_requests": {
            "correlation_trace_id",
            "execution_trace_id",
            "execution_status",
        },
        "tool_invocation_logs": {"trace_id", "approval_id"},
        "push_logs": {"idempotency_key"},
    }
    for table_name, expected in expected_columns.items():
        columns = await sqlite_database.fetch_all(f"PRAGMA table_info({table_name})")
        assert expected <= {column["name"] for column in columns}
    sqlite_index = await sqlite_database.fetch_one(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        ("uq_push_logs_idempotency",),
    )
    assert "idempotency_key" in sqlite_index["sql"]
    await sqlite_database.close()

    class RecordingPostgres:
        def __init__(self):
            self._pool = object()
            self.statements = []

        async def execute(self, sql, parameters=()):
            self.statements.append(sql)
            return 0

        async def fetch_one(self, sql, parameters=()):
            if "pg_extension" in sql:
                return {"extversion": "0.8.1"}
            if "vector_index_versions" in sql:
                return {
                    "index_name": "knowledge_vectors_bge_m3_v1",
                    "model_name": "BAAI/bge-m3",
                    "model_version": "local-bge-m3-1024-v1",
                    "dimension": 1024,
                    "status": "READY",
                }
            return None

    postgres = RecordingPostgres()
    await init_database(postgres)
    ddl = "\n".join(postgres.statements)
    assert "correlation_trace_id" in ddl
    assert "execution_trace_id" in ddl
    assert "execution_status" in ddl
    assert "tool_invocation_logs ADD COLUMN IF NOT EXISTS trace_id" in ddl
    assert "push_logs ADD COLUMN IF NOT EXISTS idempotency_key" in ddl
    assert "uq_push_logs_idempotency" in ddl


@pytest.mark.asyncio
async def test_sqlite_and_postgres_schema_include_event_workflow_relationships(tmp_path):
    database_path = tmp_path / "legacy-workflow-schema.db"
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, venue_id TEXT NOT NULL, session_id TEXT NOT NULL,
                description TEXT NOT NULL, status TEXT DEFAULT 'PENDING',
                created_at REAL, updated_at REAL
            )
            """
        )
        await connection.execute(
            """
            INSERT INTO tasks (
                id, venue_id, session_id, description, status, created_at, updated_at
            ) VALUES ('legacy-task-01', 'venue-alpha', 'session-01', '旧任务',
                'PENDING', 1710000000, 1710000000)
            """
        )
        await connection.execute(
            """
            CREATE TABLE task_decompositions (
                decomposition_id TEXT PRIMARY KEY, venue_id TEXT NOT NULL,
                requested_by TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL, session_id TEXT NOT NULL,
                trace_id TEXT NOT NULL, status TEXT NOT NULL,
                task_ids TEXT NOT NULL DEFAULT '[]', response_json TEXT, error TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE approval_requests (
                approval_id TEXT PRIMARY KEY, venue_id TEXT NOT NULL,
                tool_name TEXT NOT NULL, args TEXT NOT NULL, session_id TEXT,
                user_id TEXT, requested_at REAL NOT NULL, requested_by TEXT,
                status TEXT DEFAULT 'PENDING', reviewed_at REAL, reviewed_by TEXT,
                comment TEXT
            )
            """
        )
        await connection.execute(
            """
            INSERT INTO approval_requests (
                approval_id, venue_id, tool_name, args, session_id, user_id,
                requested_at, requested_by, status
            ) VALUES ('legacy-approval-01', 'venue-alpha', 'send_in_app_alert',
                '{}', 'session-01', 'operator-01', 1710000000, 'operator-01', 'PENDING')
            """
        )
        await connection.commit()

    sqlite_database = AsyncDBClient(database_path)
    await init_database(sqlite_database)
    expected_columns = {
        "tasks": {
            "business_id",
            "event_id",
            "due_at",
            "result_schema_json",
            "evidence_refs_json",
        },
        "task_decompositions": {"event_id"},
        "approval_requests": {
            "business_id",
            "event_id",
            "task_id",
            "supersedes_approval_id",
            "idempotency_key",
            "evidence_snapshot_json",
        },
        "event_activities": {
            "id",
            "venue_id",
            "event_id",
            "session_id",
            "message_id",
            "trace_id",
            "activity_type",
            "payload_json",
            "idempotency_key",
            "created_by",
            "created_at",
        },
    }
    for table_name, expected in expected_columns.items():
        columns = await sqlite_database.fetch_all(f"PRAGMA table_info({table_name})")
        assert expected <= {column["name"] for column in columns}

    legacy_task = await sqlite_database.fetch_one(
        "SELECT id, business_id, description FROM tasks WHERE id = ?",
        ("legacy-task-01",),
    )
    legacy_approval = await sqlite_database.fetch_one(
        "SELECT approval_id, business_id, tool_name FROM approval_requests WHERE approval_id = ?",
        ("legacy-approval-01",),
    )
    assert legacy_task["description"] == "旧任务"
    assert legacy_task["business_id"].startswith("RW-")
    assert legacy_approval["tool_name"] == "send_in_app_alert"
    assert legacy_approval["business_id"].startswith("SP-")

    await sqlite_database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, channel, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'SUCCEEDED', 'WEB', ?, ?)
        """,
        (
            "message-legacy-event",
            "trace-legacy-event",
            "session-01",
            "operator-01",
            "venue-alpha",
            "东门设备异常",
            1710000000,
            1710000000,
        ),
    )
    await sqlite_database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, push_id, from_user, raw_text, event_type,
            severity, memory_content, created_at, confirmed_at, venue_id,
            source_type, status, trace_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'LIVE', 'OPEN', ?, ?)
        """,
        (
            "legacy-event-01",
            "SJ-20240310-LEGACYEV",
            "message-legacy-event",
            "operator-01",
            "东门设备异常",
            "设施故障",
            "P1",
            "东门设备异常",
            1710000000,
            1710000000,
            "venue-alpha",
            "trace-legacy-event",
            1710000000,
        ),
    )
    await sqlite_database.execute(
        """
        INSERT INTO task_decompositions (
            decomposition_id, venue_id, requested_by, idempotency_key,
            request_fingerprint, session_id, trace_id, status, task_ids,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SUCCEEDED', ?, ?, ?)
        """,
        (
            "legacy-decomposition-01",
            "venue-alpha",
            "operator-01",
            "legacy-decomposition-key",
            "legacy-decomposition-fingerprint",
            "session-01",
            "trace-legacy-event",
            '["legacy-task-01"]',
            1710000000,
            1710000000,
        ),
    )
    await sqlite_database.execute(
        "UPDATE tasks SET decomposition_id = ? WHERE id = ?",
        ("legacy-decomposition-01", "legacy-task-01"),
    )
    await init_database(sqlite_database)
    await init_database(sqlite_database)
    activity_rows = await sqlite_database.fetch_all(
        "SELECT * FROM event_activities WHERE event_id = ?",
        ("legacy-event-01",),
    )
    assert len(activity_rows) == 1
    assert activity_rows[0]["activity_type"] == "EVENT_CREATED"
    assert activity_rows[0]["session_id"] == "session-01"
    assert activity_rows[0]["message_id"] == "message-legacy-event"
    assert activity_rows[0]["trace_id"] == "trace-legacy-event"

    linked_task = await sqlite_database.fetch_one(
        "SELECT event_id FROM tasks WHERE id = ?",
        ("legacy-task-01",),
    )
    linked_decomposition = await sqlite_database.fetch_one(
        "SELECT event_id FROM task_decompositions WHERE decomposition_id = ?",
        ("legacy-decomposition-01",),
    )
    linked_approval = await sqlite_database.fetch_one(
        "SELECT event_id FROM approval_requests WHERE approval_id = ?",
        ("legacy-approval-01",),
    )
    assert linked_task["event_id"] == "legacy-event-01"
    assert linked_decomposition["event_id"] == "legacy-event-01"
    assert linked_approval["event_id"] == "legacy-event-01"

    index_rows = await sqlite_database.fetch_all(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    )
    index_names = {row["name"] for row in index_rows}
    assert {
        "uq_tasks_business_id",
        "idx_tasks_event",
        "idx_task_decomposition_event",
        "uq_approval_business_id",
        "idx_approval_event",
        "idx_approval_task",
        "uq_approval_idempotency",
        "idx_event_activities_event",
        "idx_event_activities_trace",
        "uq_event_activities_idempotency",
    } <= index_names
    await sqlite_database.close()

    class RecordingPostgres:
        def __init__(self):
            self._pool = object()
            self.statements = []

        async def execute(self, sql, parameters=()):
            self.statements.append(sql)
            return 0

        async def fetch_one(self, sql, parameters=()):
            if "pg_extension" in sql:
                return {"extversion": "0.8.1"}
            if "vector_index_versions" in sql:
                return {
                    "index_name": "knowledge_vectors_bge_m3_v1",
                    "model_name": "BAAI/bge-m3",
                    "model_version": "local-bge-m3-1024-v1",
                    "dimension": 1024,
                    "status": "READY",
                }
            return None

    postgres = RecordingPostgres()
    await init_database(postgres)
    ddl = "\n".join(postgres.statements)
    for required_fragment in (
        "CREATE TABLE IF NOT EXISTS event_activities",
        "tasks ADD COLUMN IF NOT EXISTS business_id",
        "tasks ADD COLUMN IF NOT EXISTS event_id",
        "task_decompositions ADD COLUMN IF NOT EXISTS event_id",
        "approval_requests ADD COLUMN IF NOT EXISTS business_id",
        "approval_requests ADD COLUMN IF NOT EXISTS event_id",
        "approval_requests ADD COLUMN IF NOT EXISTS task_id",
        "approval_requests ADD COLUMN IF NOT EXISTS evidence_snapshot_json",
        "INSERT INTO event_activities",
        "uq_tasks_business_id",
        "uq_approval_business_id",
        "uq_event_activities_idempotency",
    ):
        assert required_fragment in ddl
