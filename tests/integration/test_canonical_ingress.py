import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.auth import require_auth
from src.memory_palace.api.v1.router import router as v1_router
from src.memory_palace.core.message_runs import MessageRunRepository
from src.memory_palace.core.permissions import get_permission_engine
from src.memory_palace.core.queue_worker import set_message_queue
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database


async def _build_app(tmp_path):
    db = AsyncDBClient(tmp_path / "canonical-ingress.db")
    await init_database(db)
    now = time.time()
    for venue_id, name in (("venue-west", "West Park"), ("venue-east", "East Park")):
        await db.execute(
            """
            INSERT INTO venues (id, name, status, created_at, updated_at)
            VALUES (?, ?, 'ACTIVE', ?, ?)
            """,
            (venue_id, name, now, now),
        )
    for user in (
        ("operator-west", "operator-west", "West Operator", "operator", "venue-west", "ACTIVE"),
        ("manager-west", "manager-west", "West Manager", "manager", "venue-west", "ACTIVE"),
        ("disabled-west", "disabled-west", "Disabled Operator", "operator", "venue-west", "DISABLED"),
        ("operator-east", "operator-east", "East Operator", "operator", "venue-east", "ACTIVE"),
    ):
        await db.execute(
            """
            INSERT INTO users (
                id, username, password_hash, display_name, role, venue_id,
                status, created_at, updated_at
            ) VALUES (?, ?, 'test-password-hash', ?, ?, ?, ?, ?, ?)
            """,
            (user[0], user[1], user[2], user[3], user[4], user[5], now, now),
        )
    await db.execute(
        "UPDATE users SET department = ?, job_title = ? WHERE id = ?",
        ("现场运营部", "东门运营员", "operator-west"),
    )
    await db.execute(
        "UPDATE users SET department = ?, job_title = ? WHERE id = ?",
        ("运营指挥中心", "当日值班经理", "manager-west"),
    )
    await db.execute(
        """
        INSERT INTO system_settings (
            venue_id, setting_key, setting_value, value_type, updated_by, updated_at
        ) VALUES (?, 'organization_name', ?, 'string', ?, ?)
        """,
        ("venue-west", "西岭文旅集团", "manager-west", now),
    )
    for identity_id, external_user_id, user_id in (
        ("identity-operator-west", "wecom-operator-001", "operator-west"),
        ("identity-manager-west", "wecom-manager-001", "manager-west"),
    ):
        await db.execute(
            """
            INSERT INTO channel_identities (
                id, venue_id, channel, external_tenant_id, external_user_id,
                user_id, status, created_at, updated_at
            ) VALUES (?, 'venue-west', 'WECOM', 'corp-west', ?, ?, 'ACTIVE', ?, ?)
            """,
            (identity_id, external_user_id, user_id, now, now),
        )

    queue = asyncio.Queue()
    set_message_queue(queue)
    app = FastAPI()
    app.state.db_client = db
    app.state.test_principal = {
        "user_id": "operator-west",
        "username": "operator-west",
        "role": "operator",
        "venue_id": "venue-west",
        "auth_type": "test",
    }

    async def authenticated_principal():
        return app.state.test_principal

    app.dependency_overrides[require_auth] = authenticated_principal
    app.include_router(v1_router)
    return app, queue, db


@pytest.mark.asyncio
async def test_web_message_replay_returns_original_run_without_duplicate_queue_entry(tmp_path):
    app, queue, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    request_body = {
        "channel": "WEB",
        "content": "The east gate escalator stopped.",
        "external_message_id": "web-message-001",
        "external_conversation_id": "web-conversation-001",
    }

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/api/v1/assistant/messages", json=request_body)
            replay = await client.post(
                "/api/v1/assistant/messages",
                json={**request_body, "content": "A replay must not replace the original content."},
            )

        assert first.status_code == 202
        assert replay.status_code == 202
        first_body = first.json()
        replay_body = replay.json()
        assert first_body["channel"] == "WEB"
        assert first_body["external_message_id"] == "web-message-001"
        assert first_body["external_conversation_id"] == "web-conversation-001"
        assert first_body["duplicate"] is False
        assert first_body["reply_text"] is None
        assert replay_body["duplicate"] is True
        assert replay_body["message_id"] == first_body["message_id"]
        assert replay_body["trace_id"] == first_body["trace_id"]
        assert replay_body["session_id"] == first_body["session_id"]
        assert queue.qsize() == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_simulator_lists_only_active_tenant_identities_and_uses_selected_employee(tmp_path):
    app, queue, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            identities_response = await client.get("/api/v1/channels/simulator-identities")
            accepted_response = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "operator-west",
                    "content": "The east gate escalator stopped.",
                    "external_message_id": "sim-message-001",
                    "external_conversation_id": "sim-conversation-001",
                    "metadata": {"venue_id": "venue-east"},
                },
            )

        assert identities_response.status_code == 200
        identities = identities_response.json()["identities"]
        assert {item["user_id"] for item in identities} == {"operator-west", "manager-west"}
        assert all(item["venue_id"] == "venue-west" for item in identities)
        assert all(item["status"] == "ACTIVE" for item in identities)
        operator_identity = next(item for item in identities if item["user_id"] == "operator-west")
        assert operator_identity["organization_name"] == "西岭文旅集团"
        assert operator_identity["venue_name"] == "West Park"
        assert operator_identity["department"] == "现场运营部"
        assert operator_identity["job_title"] == "东门运营员"
        assert operator_identity["external_tenant_id"] == "corp-west"
        assert operator_identity["external_user_id"] == "wecom-operator-001"
        assert operator_identity["wecom_binding_status"] == "ACTIVE"

        assert accepted_response.status_code == 202
        accepted = accepted_response.json()
        assert accepted["channel"] == "WECOM_SIMULATOR"
        assert accepted["identity"]["user_id"] == "operator-west"
        assert accepted["identity"]["venue_id"] == "venue-west"
        queued = queue.get_nowait()
        assert queued["from_user"] == "operator-west"
        assert queued["venue_id"] == "venue-west"
        assert queued["metadata"]["venue_id"] == "venue-west"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_real_wecom_adapter_rejects_before_persistence_even_when_credentials_exist(
    tmp_path,
    monkeypatch,
):
    for key, value in {
        "WECHAT_TOKEN": "configured-token",
        "WECHAT_ENCODING_AES_KEY": "a" * 43,
        "WECHAT_CORP_ID": "configured-corp",
        "WECHAT_CORP_SECRET": "configured-secret",
        "WECHAT_AGENT_ID": "1000002",
    }.items():
        monkeypatch.setenv(key, value)
    app, queue, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "api:test",
        "username": "api-client",
        "role": "api",
        "venue_id": "venue-west",
        "auth_type": "api_key",
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/channels/wecom/messages",
                json={
                    "content": "东门扶梯突然停运",
                    "external_message_id": "wecom-disabled-001",
                    "external_conversation_id": "wecom-conversation-001",
                    "external_tenant_id": "corp-west",
                    "external_user_id": "wecom-operator-001",
                },
            )

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "INTEGRATION_DISABLED"
        assert response.json()["detail"]["policy_mode"] == "WECOM_SIMULATOR_ONLY"
        assert queue.empty()
        assert await db.fetch_one(
            "SELECT message_id FROM message_runs WHERE external_message_id = ?",
            ("wecom-disabled-001",),
        ) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_simulator_hides_and_rejects_active_employee_without_wecom_binding(tmp_path):
    app, queue, db = await _build_app(tmp_path)
    now = time.time()
    await db.execute(
        """
        INSERT INTO users (
            id, username, password_hash, display_name, role, venue_id,
            status, created_at, updated_at
        ) VALUES (?, ?, 'test-password-hash', ?, 'operator', ?, 'ACTIVE', ?, ?)
        """,
        (
            "unbound-west",
            "unbound-west",
            "Unbound West Operator",
            "venue-west",
            now,
            now,
        ),
    )
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            identities_response = await client.get("/api/v1/channels/simulator-identities")
            rejected = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "unbound-west",
                    "content": "未绑定企微身份不应进入消息队列。",
                    "external_message_id": "sim-unbound-001",
                    "external_conversation_id": "sim-unbound-conversation-001",
                },
            )

        assert identities_response.status_code == 200, identities_response.text
        assert "unbound-west" not in {
            item["user_id"] for item in identities_response.json()["identities"]
        }
        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["detail"]["code"] == "IDENTITY_NOT_BOUND"
        assert queue.empty()
        assert await db.fetch_one(
            "SELECT message_id FROM message_runs WHERE external_message_id = ?",
            ("sim-unbound-001",),
        ) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_simulator_attachment_upload_survives_message_replay_and_history_refresh(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ATTACHMENT_STORAGE_DIR", str(tmp_path / "attachment-objects"))
    app, queue, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"safe-wheel-image"

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/v1/channels/simulator/attachments",
                data={"user_id": "operator-west"},
                files={"file": ("right-wheel.png", image_bytes, "image/png")},
            )
            assert uploaded.status_code == 201, uploaded.text
            attachment = uploaded.json()["attachment"]
            request_body = {
                "user_id": "operator-west",
                "content": "12号观光车右后轮异响，现场图片已上传。",
                "external_message_id": "sim-attachment-001",
                "external_conversation_id": "sim-attachment-conversation-001",
                "attachments": [
                    {
                        "attachment_id": attachment["attachment_id"],
                        "description": "右后轮内侧有水迹，车辆已断电。",
                    }
                ],
            }
            accepted = await client.post(
                "/api/v1/channels/simulator/messages",
                json=request_body,
            )
            replayed = await client.post(
                "/api/v1/channels/simulator/messages",
                json=request_body,
            )
            history = await client.get(
                f"/api/v1/assistant/sessions/{accepted.json()['session_id']}/messages",
                params={"acting_user_id": "operator-west"},
            )
            content = await client.get(attachment["external_ref"])

        assert attachment["name"] == "right-wheel.png"
        assert attachment["content_type"] == "image/png"
        assert attachment["size_bytes"] == len(image_bytes)
        assert attachment["scan_status"] == "PASSED"
        assert attachment["external_ref"].startswith(
            "/api/v1/assistant/attachments/"
        )
        assert accepted.status_code == 202, accepted.text
        assert replayed.status_code == 202, replayed.text
        assert replayed.json()["duplicate"] is True
        assert replayed.json()["message_id"] == accepted.json()["message_id"]
        assert queue.qsize() == 1
        assert history.status_code == 200, history.text
        user_message = next(
            item for item in history.json()["messages"] if item["role"] == "user"
        )
        assert len(user_message["attachments"]) == 1
        restored_attachment = user_message["attachments"][0]
        assert restored_attachment["attachment_id"] == attachment["attachment_id"]
        assert restored_attachment["description"] == "右后轮内侧有水迹，车辆已断电。"
        assert restored_attachment["uploaded_by_name"] == "West Operator"
        assert content.status_code == 200, content.text
        assert content.headers["content-type"].startswith("image/png")
        assert content.content == image_bytes
        links = await db.fetch_all(
            "SELECT * FROM message_attachment_links WHERE message_id = ?",
            (accepted.json()["message_id"],),
        )
        assert len(links) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_employee_retries_own_dead_letter_once_without_duplicate_business_result(
    tmp_path,
):
    app, queue, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    retry_calls = []

    async def retry_dead_letter(dead_letter_id):
        retry_calls.append(dead_letter_id)
        return {
            "dead_letter_id": dead_letter_id,
            "stream_message_id": "redis-manual-retry-001",
            "message_id": "",
        }

    queue.retry_dead_letter = retry_dead_letter
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "operator-west",
                    "content": "请把护板间隙检查整理成我的今日待办",
                    "external_message_id": "sim-retry-required-001",
                    "external_conversation_id": "sim-retry-required-conversation-001",
                },
            )
            message_id = accepted.json()["message_id"]
            await db.execute(
                """
                UPDATE message_runs
                SET status = 'RETRY_REQUIRED', attempt_count = 4,
                    error = '模型服务暂时不可用',
                    dead_letter_id = 'dead-letter-sim-001', processed_at = ?
                WHERE message_id = ?
                """,
                (time.time(), message_id),
            )

            failed_history = await client.get(
                f"/api/v1/assistant/sessions/{accepted.json()['session_id']}/messages",
                params={"acting_user_id": "operator-west"},
            )
            internal_dead_letter = await db.fetch_one(
                "SELECT dead_letter_id FROM message_runs WHERE message_id = ?",
                (message_id,),
            )
            first_retry = await client.post(
                f"/api/v1/assistant/messages/{message_id}/retry",
                params={"acting_user_id": "operator-west"},
            )
            duplicate_retry = await client.post(
                f"/api/v1/assistant/messages/{message_id}/retry",
                params={"acting_user_id": "operator-west"},
            )
            history = await client.get(
                f"/api/v1/assistant/sessions/{accepted.json()['session_id']}/messages",
                params={"acting_user_id": "operator-west"},
            )

        assert failed_history.status_code == 200, failed_history.text
        failed_assistant_message = next(
            item for item in failed_history.json()["messages"] if item["role"] == "assistant"
        )
        assert failed_assistant_message["message_id"] == message_id
        assert failed_assistant_message["status"] == "RETRY_REQUIRED"
        assert "dead_letter_id" not in failed_assistant_message
        assert internal_dead_letter["dead_letter_id"] == "dead-letter-sim-001"
        assert first_retry.status_code == 202, first_retry.text
        assert first_retry.json()["message_id"] == message_id
        assert first_retry.json()["status"] == "RETRYING"
        assert first_retry.json()["manual_retry_count"] == 1
        assert duplicate_retry.status_code == 409, duplicate_retry.text
        assert retry_calls == ["dead-letter-sim-001"]
        assistant_message = next(
            item for item in history.json()["messages"] if item["role"] == "assistant"
        )
        assert assistant_message["message_id"] == message_id
        assert assistant_message["status"] == "RETRYING"
        assert assistant_message["attempt_count"] == 4
        assert assistant_message["manual_retry_count"] == 1
        assert assistant_message["retryable"] is False
        assert await db.fetch_one(
            "SELECT id FROM audit_logs WHERE action = ? AND resource_id = ?",
            ("MESSAGE_MANUAL_RETRY_REQUESTED", message_id),
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_employee_cannot_retry_another_users_or_tenants_message(tmp_path):
    app, queue, db = await _build_app(tmp_path)
    retry_calls = []

    async def retry_dead_letter(dead_letter_id):
        retry_calls.append(dead_letter_id)
        return {
            "dead_letter_id": dead_letter_id,
            "stream_message_id": "must-not-be-created",
            "message_id": "",
        }

    queue.retry_dead_letter = retry_dead_letter
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted = await client.post(
                "/api/v1/assistant/messages",
                json={
                    "content": "仅允许原员工重试",
                    "external_message_id": "web-private-retry-001",
                    "external_conversation_id": "web-private-retry-conversation-001",
                },
            )
            message_id = accepted.json()["message_id"]
            await db.execute(
                """
                UPDATE message_runs
                SET status = 'RETRY_REQUIRED', dead_letter_id = 'private-dead-letter-001'
                WHERE message_id = ?
                """,
                (message_id,),
            )

            app.state.test_principal = {
                "user_id": "manager-west",
                "username": "manager-west",
                "role": "manager",
                "venue_id": "venue-west",
                "auth_type": "test",
            }
            same_venue_other_user = await client.post(
                f"/api/v1/assistant/messages/{message_id}/retry",
                params={"acting_user_id": "manager-west"},
            )

            app.state.test_principal = {
                "user_id": "operator-east",
                "username": "operator-east",
                "role": "operator",
                "venue_id": "venue-east",
                "auth_type": "test",
            }
            other_tenant = await client.post(
                f"/api/v1/assistant/messages/{message_id}/retry",
            )

        assert same_venue_other_user.status_code == 404
        assert other_tenant.status_code == 404
        assert retry_calls == []
        persisted = await db.fetch_one(
            "SELECT status, manual_retry_count FROM message_runs WHERE message_id = ?",
            (message_id,),
        )
        assert persisted == {
            "status": "RETRY_REQUIRED",
            "manual_retry_count": 0,
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_real_wecom_message_remains_disabled_after_identity_mapping(tmp_path, monkeypatch):
    for key in (
        "WECHAT_TOKEN",
        "WECHAT_ENCODING_AES_KEY",
        "WECHAT_CORP_ID",
        "WECHAT_CORP_SECRET",
        "WECHAT_AGENT_ID",
    ):
        monkeypatch.setenv(key, "configured-for-test")
    app, queue, db = await _build_app(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            app.state.test_principal = {
                "user_id": "admin-west",
                "username": "admin-west",
                "role": "admin",
                "venue_id": "venue-west",
                "auth_type": "test",
            }
            mapped = await client.post(
                "/api/v1/channels/identities",
                json={
                    "channel": "WECOM",
                    "external_tenant_id": "corp-west",
                    "external_user_id": "wecom-operator-001",
                    "user_id": "operator-west",
                },
            )

            app.state.test_principal = {
                "user_id": "api:wecom-west",
                "username": "api-client",
                "role": "api",
                "venue_id": "venue-west",
                "auth_type": "api_key",
            }
            accepted = await client.post(
                "/api/v1/channels/wecom/messages",
                json={
                    "external_tenant_id": "corp-west",
                    "external_user_id": "wecom-operator-001",
                    "external_message_id": "wecom-message-001",
                    "external_conversation_id": "wecom-conversation-001",
                    "content": "The east gate escalator stopped.",
                },
            )

        assert mapped.status_code == 201
        assert mapped.json()["status"] == "ACTIVE"
        assert accepted.status_code == 503
        body = accepted.json()["detail"]
        assert body["code"] == "INTEGRATION_DISABLED"
        assert body["policy_mode"] == "WECOM_SIMULATOR_ONLY"
        assert queue.empty()
        assert await db.fetch_one(
            "SELECT message_id FROM message_runs WHERE external_message_id = ?",
            ("wecom-message-001",),
        ) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_manager_can_restore_selected_employee_simulator_conversation_with_cards(tmp_path):
    app, _, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "operator-west",
                    "content": "The east gate escalator stopped.",
                    "external_message_id": "sim-history-message-001",
                    "external_conversation_id": "sim-history-conversation-001",
                },
            )
            accepted = accepted_response.json()
            await MessageRunRepository(db).mark_completed(
                accepted["message_id"],
                {
                    "status": "processed",
                    "trace_id": accepted["trace_id"],
                    "route": {"target_agent": "commander"},
                    "reply_text": "A maintenance task has been created.",
                    "business_cards": [
                        {"type": "task", "id": "TASK-001", "title": "Inspect escalator"}
                    ],
                },
            )
            history = await client.get(
                f"/api/v1/assistant/sessions/{accepted['session_id']}/messages",
                params={"acting_user_id": "operator-west"},
            )

        assert history.status_code == 200
        body = history.json()
        assert body["session"]["session_id"] == accepted["session_id"]
        assert body["session"]["channel"] == "WECOM_SIMULATOR"
        assert body["identity"]["user_id"] == "operator-west"
        assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
        assert body["messages"][0]["content"] == "The east gate escalator stopped."
        assert body["messages"][1]["content"] == "A maintenance task has been created."
        assert body["messages"][1]["status"] == "COMPLETED"
        assert body["messages"][1]["business_cards"] == [
            {"type": "task", "id": "TASK-001", "title": "Inspect escalator"}
        ]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_simulator_outbox_returns_readable_controlled_action_lifecycle_without_duplicate_push(
    tmp_path,
):
    app, _, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted_response = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "operator-west",
                    "content": "东门扶梯停运，请协助处置。",
                    "external_message_id": "sim-outbox-message-001",
                    "external_conversation_id": "sim-outbox-conversation-001",
                },
            )
            session_id = accepted_response.json()["session_id"]
            now = time.time()
            approvals = (
                (
                    "approval-pending",
                    "SP-20260731-001",
                    "send_in_app_alert",
                    '{"message":"请值班经理确认现场封控。","level":"warning"}',
                    now,
                    "PENDING",
                    None,
                    "NOT_STARTED",
                    None,
                    None,
                ),
                (
                    "approval-rejected",
                    "SP-20260731-002",
                    "send_in_app_alert",
                    '{"message":"立即关闭东门通道。","level":"critical"}',
                    now + 1,
                    "REJECTED",
                    "范围过大，请仅关闭扶梯区域。",
                    "NOT_EXECUTED",
                    None,
                    None,
                ),
                (
                    "approval-succeeded",
                    "SP-20260731-003",
                    "send_in_app_alert",
                    '{"message":"扶梯区域已封控，请绕行西侧通道。","level":"warning"}',
                    now + 2,
                    "APPROVED",
                    "同意执行。",
                    "SUCCEEDED",
                    '{"status":"executed","result":{"status":"DELIVERED","push_id":"push-success"}}',
                    None,
                ),
                (
                    "approval-failed",
                    "SP-20260731-004",
                    "send_in_app_alert",
                    '{"message":"通知维保负责人到场。","level":"warning"}',
                    now + 3,
                    "APPROVED",
                    "同意执行。",
                    "FAILED",
                    '{"status":"error","message":"https://internal.example.local/outbox?token=secret"}',
                    "https://internal.example.local/outbox?token=secret",
                ),
                (
                    "approval-external-succeeded",
                    "SP-20260731-005",
                    "send_sms",
                    '{"message":"已通知维保负责人。","phone":"13800000000","priority":"high"}',
                    now + 4,
                    "APPROVED",
                    "同意执行。",
                    "SUCCEEDED",
                    '{"status":"executed","result":{"status":"accepted"}}',
                    None,
                ),
            )
            for approval in approvals:
                await db.execute(
                    """
                    INSERT INTO approval_requests (
                        approval_id, business_id, venue_id, tool_name, args,
                        session_id, user_id, requested_at, requested_by, status,
                        comment, execution_status, execution_result, execution_error
                    ) VALUES (?, ?, 'venue-west', ?, ?, ?, 'manager-west', ?,
                              'formal-client:manager-west', ?, ?, ?, ?, ?)
                    """,
                    (
                        approval[0],
                        approval[1],
                        approval[2],
                        approval[3],
                        session_id,
                        approval[4],
                        approval[5],
                        approval[6],
                        approval[7],
                        approval[8],
                        approval[9],
                    ),
                )
            await db.execute(
                """
                INSERT INTO approval_requests (
                    approval_id, business_id, venue_id, tool_name, args,
                    session_id, user_id, requested_at, requested_by,
                    supersedes_approval_id, status, execution_status
                ) VALUES (
                    'approval-resubmitted', 'SP-20260731-006', 'venue-west',
                    'send_in_app_alert',
                    '{"message":"仅关闭扶梯区域并引导游客绕行。","level":"warning"}',
                    ?, 'manager-west', ?, 'formal-client:manager-west',
                    'approval-rejected', 'PENDING', 'NOT_STARTED'
                )
                """,
                (session_id, now + 5),
            )
            await db.execute(
                """
                INSERT INTO push_logs (
                    push_id, venue_id, msg_id, from_user, raw_text, event_type,
                    severity, pushed_at, adoption_status, trace_id, channel,
                    recipient, delivery_status, idempotency_key
                ) VALUES (
                    'push-success', 'venue-west', 'approval-succeeded',
                    'manager-west', '扶梯区域已封控，请绕行西侧通道。', '站内告警',
                    'P1', ?, 'pending', 'trace-outbox-success', 'in_app', ?,
                    'DELIVERED', 'approval-succeeded'
                )
                """,
                (now + 2.5, f"session:{session_id}"),
            )
            await db.execute(
                """
                INSERT INTO push_logs (
                    push_id, venue_id, msg_id, from_user, raw_text, event_type,
                    severity, pushed_at, adoption_status, trace_id, channel,
                    recipient, delivery_status, idempotency_key
                ) VALUES (
                    'push-success-latest', 'venue-west', 'approval-succeeded',
                    'manager-west', '扶梯区域已封控，请绕行西侧通道。', '站内告警',
                    'P1', ?, 'pending', 'trace-outbox-success-latest', 'in_app', ?,
                    'DELIVERED', 'approval-succeeded:duplicate-ledger'
                )
                """,
                (now + 2.75, f"session:{session_id}"),
            )
            await db.execute(
                """
                INSERT INTO push_logs (
                    push_id, venue_id, msg_id, from_user, raw_text, event_type,
                    severity, pushed_at, adoption_status, trace_id, channel,
                    recipient, delivery_status, idempotency_key
                ) VALUES (
                    'push-wrong-recipient', 'venue-west', 'approval-succeeded',
                    'manager-west', '不应串入当前员工会话的通知', '站内告警',
                    'P1', ?, 'pending', 'trace-wrong-recipient', 'in_app',
                    'session:another-employee-session', 'DELIVERED',
                    'approval-succeeded:wrong-recipient'
                )
                """,
                (now + 20,),
            )

            response = await client.get(
                f"/api/v1/channels/simulator/sessions/{session_id}/outbox",
                params={"user_id": "operator-west"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == session_id
        assert body["user_id"] == "operator-west"
        assert len(body["items"]) == 6
        items = {item["approval_id"]: item for item in body["items"]}
        assert items["approval-pending"]["tool_label"] == "企微模拟器通知"
        assert items["approval-pending"]["status"] == "PENDING"
        assert items["approval-pending"]["status_summary"] == "等待管理员审批"
        assert items["approval-rejected"]["status"] == "REJECTED"
        assert items["approval-rejected"]["review_comment"] == "范围过大，请仅关闭扶梯区域。"
        assert items["approval-succeeded"]["status"] == "SUCCEEDED"
        assert items["approval-succeeded"]["push_id"] == "push-success-latest"
        assert items["approval-succeeded"]["delivery_status"] == "DELIVERED"
        assert items["approval-succeeded"]["message"] == "扶梯区域已封控，请绕行西侧通道。"
        assert "不应串入当前员工会话" not in str(body)
        assert items["approval-failed"]["status"] == "FAILED"
        assert items["approval-failed"]["execution_error"] == "操作失败，请携带 Trace ID 联系管理员后重试。"
        assert "internal.example.local" not in str(items["approval-failed"])
        assert items["approval-external-succeeded"]["status"] == "SUCCEEDED"
        assert items["approval-external-succeeded"]["delivery_status"] is None
        assert (
            items["approval-external-succeeded"]["status_summary"]
            == "审批通过，动作执行成功，尚无模拟器送达记录"
        )
        assert items["approval-resubmitted"]["supersedes_approval_id"] == "approval-rejected"
        assert items["approval-resubmitted"]["supersedes_business_id"] == "SP-20260731-002"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_approved_in_app_action_flows_from_real_approval_chain_into_simulator_outbox(
    tmp_path,
    monkeypatch,
):
    app, _, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})

    async def no_external_approval_notification(_approval):
        return None

    monkeypatch.setattr(engine, "_notify_admin", no_external_approval_notification)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "operator-west",
                    "content": "东门扶梯停运，请安排封控。",
                    "external_message_id": "sim-real-outbox-001",
                    "external_conversation_id": "sim-real-outbox-conversation-001",
                },
            )
            accepted_body = accepted.json()
            session_id = accepted_body["session_id"]
            now = time.time()
            await db.execute(
                """
                INSERT INTO confirmed_events (
                    event_id, business_id, push_id, from_user, raw_text,
                    event_type, severity, context_trigger_data, memory_content,
                    created_at, confirmed_at, venue_id, source_type, status,
                    trace_id, updated_at
                ) VALUES (
                    'event-real-outbox-001', 'SJ-20260731-OUTBOX01', ?,
                    'operator-west', '东门扶梯停运，请安排封控。', '设备异常',
                    'P1', '{}', '东门扶梯停运事件', ?, ?, 'venue-west',
                    'LIVE', 'OPEN', ?, ?
                )
                """,
                (accepted_body["message_id"], now, now, accepted_body["trace_id"], now),
            )
            await db.execute(
                """
                INSERT INTO tasks (
                    id, business_id, venue_id, session_id, event_id,
                    description, status, dependencies, result_schema_json,
                    evidence_refs_json, result, assigned_user_id,
                    created_at, updated_at, completed_at
                ) VALUES (
                    'task-real-outbox-001', 'RW-20260731-OUTBOX01',
                    'venue-west', ?, 'event-real-outbox-001',
                    '确认扶梯停运并完成现场封控', 'DONE', '[]', '{}', '[]',
                    '{"closed":true}', 'operator-west', ?, ?, ?
                )
                """,
                (session_id, now, now, now),
            )

            requested = await client.post(
                "/api/v1/admin/action-requests",
                headers={"Idempotency-Key": "simulator-real-outbox-approval-001"},
                json={
                    "tool_name": "send_in_app_alert",
                    "session_id": session_id,
                    "event_id": "event-real-outbox-001",
                    "task_id": "task-real-outbox-001",
                    "message": "东门扶梯区域已封控，请员工引导游客从西侧绕行。",
                    "priority": "warning",
                },
            )
            assert requested.status_code == 202, requested.text
            approval_id = requested.json()["approval_id"]
            pending = await client.get(
                f"/api/v1/channels/simulator/sessions/{session_id}/outbox",
                params={"user_id": "operator-west"},
            )

            approved = await client.post(
                f"/api/v1/admin/approvals/{approval_id}/approve",
                json={"comment": "处置依据完整，同意发送。"},
            )
            completed = await client.get(
                f"/api/v1/channels/simulator/sessions/{session_id}/outbox",
                params={"user_id": "operator-west"},
            )

        assert pending.status_code == 200
        assert len(pending.json()["items"]) == 1
        assert pending.json()["items"][0]["status"] == "PENDING"
        assert pending.json()["items"][0]["status_summary"] == "等待管理员审批"
        assert approved.status_code == 200, approved.text
        assert completed.status_code == 200
        assert len(completed.json()["items"]) == 1
        item = completed.json()["items"][0]
        assert item["approval_id"] == approval_id
        assert item["status"] == "SUCCEEDED"
        assert item["delivery_status"] == "DELIVERED"
        assert item["push_id"]
        assert item["review_comment"] == "处置依据完整，同意发送。"
        assert item["message"] == "东门扶梯区域已封控，请员工引导游客从西侧绕行。"
        persisted_push = await db.fetch_one(
            "SELECT * FROM push_logs WHERE push_id = ? AND venue_id = ?",
            (item["push_id"], "venue-west"),
        )
        assert persisted_push["recipient"] == f"session:{session_id}"
        assert persisted_push["idempotency_key"] == approval_id
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_event_participant_fanout_is_visible_only_in_each_frozen_simulator_session(
    tmp_path,
    monkeypatch,
):
    app, _, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})

    async def no_external_approval_notification(_approval):
        return None

    monkeypatch.setattr(engine, "_notify_admin", no_external_approval_notification)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        now = time.time()
        await db.execute(
            """
            INSERT INTO users (
                id, username, password_hash, display_name, role, venue_id,
                department, job_title, status, created_at, updated_at
            ) VALUES (
                'worker-west', 'worker-west', 'test-password-hash', '王芳',
                'operator', 'venue-west', '设备保障部', '设备维修员',
                'ACTIVE', ?, ?
            )
            """,
            (now, now),
        )
        await db.execute(
            """
            INSERT INTO channel_identities (
                id, venue_id, channel, external_tenant_id, external_user_id,
                user_id, status, created_at, updated_at
            ) VALUES (
                'identity-worker-west', 'venue-west', 'WECOM', 'corp-west',
                'wecom-worker-001', 'worker-west', 'ACTIVE', ?, ?
            )
            """,
            (now, now),
        )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            sessions = {}
            for key, user_id, external_user_id in (
                ("reporter_old", "operator-west", "fanout-reporter-old"),
                ("reporter_new", "operator-west", "fanout-reporter-new"),
                ("owner", "manager-west", "fanout-owner"),
                ("worker", "worker-west", "fanout-worker"),
            ):
                opened = await client.post(
                    "/api/v1/channels/simulator/messages",
                    json={
                        "user_id": user_id,
                        "content": f"建立 {key} 演示会话。",
                        "external_message_id": f"sim-{external_user_id}-message",
                        "external_conversation_id": f"sim-{external_user_id}-conversation",
                    },
                )
                assert opened.status_code == 202, opened.text
                sessions[key] = opened.json()["session_id"]

            await db.execute(
                """
                INSERT INTO confirmed_events (
                    event_id, business_id, push_id, from_user, raw_text,
                    event_type, severity, context_trigger_data, memory_content,
                    created_at, confirmed_at, venue_id, source_type, status,
                    assigned_to, trace_id, updated_at
                ) VALUES (
                    'event-fanout-outbox-001', 'SJ-20260731-FANOUT01',
                    'message-fanout-outbox-001', 'operator-west',
                    '东门扶梯停运，请相关人员协同处置。', '设备异常', 'P1', '{}',
                    '东门扶梯停运事件', ?, ?, 'venue-west', 'LIVE', 'OPEN',
                    'manager-west', 'trace-fanout-outbox', ?
                )
                """,
                (now, now, now),
            )
            await db.execute(
                """
                INSERT INTO tasks (
                    id, business_id, venue_id, session_id, event_id,
                    description, status, dependencies, result_schema_json,
                    evidence_refs_json, result, assigned_user_id,
                    created_at, updated_at, completed_at
                ) VALUES (
                    'task-fanout-outbox-001', 'RW-20260731-FANOUT01',
                    'venue-west', ?, 'event-fanout-outbox-001',
                    '完成扶梯停运和现场封控', 'DONE', '[]', '{}', '[]',
                    '{"closed":true}', 'worker-west', ?, ?, ?
                )
                """,
                (sessions["reporter_old"], now, now, now),
            )

            requested = await client.post(
                "/api/v1/admin/action-requests",
                headers={"Idempotency-Key": "simulator-fanout-outbox-001"},
                json={
                    "tool_name": "send_in_app_alert",
                    "recipient_scope": "EVENT_PARTICIPANTS",
                    "session_id": sessions["reporter_old"],
                    "event_id": "event-fanout-outbox-001",
                    "task_id": "task-fanout-outbox-001",
                    "message": "扶梯区域已封控，请三位相关人员同步后续进展。",
                    "priority": "warning",
                },
            )
            assert requested.status_code == 202, requested.text
            approval_id = requested.json()["approval_id"]
            frozen = await db.fetch_one(
                "SELECT evidence_snapshot_json FROM approval_requests WHERE approval_id = ?",
                (approval_id,),
            )
            frozen_targets = json.loads(frozen["evidence_snapshot_json"])["delivery"]["targets"]
            assert {
                target["user_id"]: target["session_id"]
                for target in frozen_targets
            } == {
                "operator-west": sessions["reporter_new"],
                "manager-west": sessions["owner"],
                "worker-west": sessions["worker"],
            }

            pending_results = {}
            for key, user_id in (
                ("reporter_new", "operator-west"),
                ("owner", "manager-west"),
                ("worker", "worker-west"),
            ):
                response = await client.get(
                    f"/api/v1/channels/simulator/sessions/{sessions[key]}/outbox",
                    params={"user_id": user_id},
                )
                assert response.status_code == 200, response.text
                pending_results[key] = response.json()["items"]

            pending_old_source = await client.get(
                f"/api/v1/channels/simulator/sessions/{sessions['reporter_old']}/outbox",
                params={"user_id": "operator-west"},
            )

            approved = await client.post(
                f"/api/v1/admin/approvals/{approval_id}/approve",
                json={"comment": "同意发送到企微模拟器。"},
            )
            assert approved.status_code == 200, approved.text

            target_results = {}
            for key, user_id in (
                ("reporter_new", "operator-west"),
                ("owner", "manager-west"),
                ("worker", "worker-west"),
            ):
                response = await client.get(
                    f"/api/v1/channels/simulator/sessions/{sessions[key]}/outbox",
                    params={"user_id": user_id},
                )
                assert response.status_code == 200, response.text
                target_results[key] = response.json()["items"]

            old_source = await client.get(
                f"/api/v1/channels/simulator/sessions/{sessions['reporter_old']}/outbox",
                params={"user_id": "operator-west"},
            )
            app.state.test_principal = {
                "user_id": "operator-east",
                "username": "operator-east",
                "role": "manager",
                "venue_id": "venue-east",
                "auth_type": "test",
            }
            cross_tenant = await client.get(
                f"/api/v1/channels/simulator/sessions/{sessions['owner']}/outbox",
                params={"user_id": "manager-west"},
            )

        for key, items in pending_results.items():
            assert len(items) == 1
            assert items[0]["approval_id"] == approval_id
            assert items[0]["session_id"] == sessions[key]
            assert items[0]["status"] == "PENDING"
            assert items[0]["approval_status"] == "PENDING"
            assert items[0]["execution_status"] == "NOT_STARTED"
            assert items[0]["delivery_status"] is None
        assert pending_old_source.status_code == 200
        assert pending_old_source.json()["items"] == []
        for key, items in target_results.items():
            assert len(items) == 1
            assert items[0]["approval_id"] == approval_id
            assert items[0]["session_id"] == sessions[key]
            assert items[0]["delivery_status"] == "DELIVERED"
            assert items[0]["status"] == "SUCCEEDED"
        assert old_source.status_code == 200
        assert old_source.json()["items"] == []
        assert cross_tenant.status_code == 404
        pushes = await db.fetch_all(
            """
            SELECT recipient FROM push_logs
            WHERE venue_id = 'venue-west' AND msg_id = ?
              AND channel = 'WECOM_SIMULATOR_OUTBOX'
            ORDER BY recipient
            """,
            (approval_id,),
        )
        assert {row["recipient"] for row in pushes} == {
            f"session:{sessions['owner']}",
            f"session:{sessions['reporter_new']}",
            f"session:{sessions['worker']}",
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_simulator_outbox_isolated_by_operator_role_tenant_employee_and_session(tmp_path):
    app, _, db = await _build_app(tmp_path)
    app.state.test_principal = {
        "user_id": "manager-west",
        "username": "manager-west",
        "role": "manager",
        "venue_id": "venue-west",
        "auth_type": "test",
    }
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            accepted = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "operator-west",
                    "content": "创建一条隔离测试会话。",
                    "external_message_id": "sim-outbox-isolation-001",
                    "external_conversation_id": "sim-outbox-isolation-conversation-001",
                },
            )
            session_id = accepted.json()["session_id"]
            second = await client.post(
                "/api/v1/channels/simulator/messages",
                json={
                    "user_id": "operator-west",
                    "content": "创建同一员工的第二条隔离测试会话。",
                    "external_message_id": "sim-outbox-isolation-002",
                    "external_conversation_id": "sim-outbox-isolation-conversation-002",
                },
            )
            second_session_id = second.json()["session_id"]
            await db.execute(
                """
                INSERT INTO approval_requests (
                    approval_id, business_id, venue_id, tool_name, args,
                    session_id, user_id, requested_at, requested_by, status,
                    execution_status
                ) VALUES (
                    'approval-second-session', 'SP-20260731-SECOND', 'venue-west',
                    'send_in_app_alert', '{"message":"仅属于第二会话"}', ?,
                    'manager-west', ?, 'formal-client:manager-west', 'PENDING',
                    'NOT_STARTED'
                )
                """,
                (second_session_id, time.time()),
            )

            first_session = await client.get(
                f"/api/v1/channels/simulator/sessions/{session_id}/outbox",
                params={"user_id": "operator-west"},
            )

            wrong_employee = await client.get(
                f"/api/v1/channels/simulator/sessions/{session_id}/outbox",
                params={"user_id": "manager-west"},
            )
            app.state.test_principal = {
                "user_id": "operator-east",
                "username": "operator-east",
                "role": "manager",
                "venue_id": "venue-east",
                "auth_type": "test",
            }
            cross_tenant_principal = await client.get(
                f"/api/v1/channels/simulator/sessions/{session_id}/outbox",
                params={"user_id": "operator-west"},
            )
            app.state.test_principal = {
                "user_id": "operator-west",
                "username": "operator-west",
                "role": "operator",
                "venue_id": "venue-west",
                "auth_type": "test",
            }
            employee_direct_access = await client.get(
                f"/api/v1/channels/simulator/sessions/{session_id}/outbox",
                params={"user_id": "operator-west"},
            )

        assert first_session.status_code == 200
        assert first_session.json()["items"] == []
        assert wrong_employee.status_code == 404
        assert cross_tenant_principal.status_code == 404
        assert employee_direct_access.status_code == 403
    finally:
        await db.close()
