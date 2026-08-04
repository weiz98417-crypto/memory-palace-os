import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.v1.endpoints.admin import router as admin_router
from src.memory_palace.api.v1.endpoints.auth import bootstrap_identity_store, router as auth_router
from src.memory_palace.api.v1.endpoints.channels import router as channels_router
from src.memory_palace.api.v1.endpoints.knowledge import router as knowledge_router
from src.memory_palace.api.v1.endpoints.management import router as management_router
from src.memory_palace.api.v1.endpoints.sessions import router as sessions_router
from src.memory_palace.api.v1.endpoints.skills import router as skills_router
from src.memory_palace.api.v1.endpoints.watcher import router as watcher_router
from src.memory_palace.api.v1.endpoints.workflows import router as workflows_router
from src.memory_palace.api.errors import install_error_handlers
from src.memory_palace.core.task_graph import TaskGraph
from src.memory_palace.core.watcher_runtime import (
    recover_interrupted_watcher_runs,
    run_watcher_policy,
)
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.skills.persona_extract.skill import PersonaExtractSkill
from src.memory_palace.tools.llm_wrapper import LLMResponse


class VectorStoreStub:
    def __init__(self):
        self.documents = {}

    def health(self):
        return {"status": "healthy", "backend": "test_stub"}

    def upsert_experience(self, text, metadata, doc_id, strict=False):
        self.documents[doc_id] = {"text": text, "metadata": dict(metadata)}
        return True

    def delete_experience(self, doc_id, strict=False):
        if strict and doc_id not in self.documents:
            raise RuntimeError("vector document missing")
        self.documents.pop(doc_id, None)
        return True

    def query_experience(self, query, top_k=5, threshold=0.0, venue_id=None, strict=False):
        results = []
        for doc_id, document in self.documents.items():
            metadata = document["metadata"]
            if venue_id and metadata.get("venue_id") != venue_id:
                continue
            if query.lower() not in document["text"].lower() and query.lower() not in metadata.get("title", "").lower():
                continue
            results.append(
                {
                    "id": doc_id,
                    "document": document["text"],
                    "metadata": metadata,
                    "similarity": 0.93,
                }
            )
        return results[:top_k]


class SchedulerStub:
    def __init__(self):
        self.reload_count = 0

    async def reload_jobs(self):
        self.reload_count += 1


async def build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "test-jwt-secret-with-more-than-32-characters")
    monkeypatch.setenv("ADMIN_USERNAME", "mvp-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "Mvp-Admin-Password-2026")
    monkeypatch.setenv("ADMIN_DISPLAY_NAME", "交付管理员")
    monkeypatch.setenv("DEFAULT_VENUE_ID", "venue-alpha")
    monkeypatch.setenv("DEFAULT_VENUE_NAME", "云栖山景区")

    database = AsyncDBClient(tmp_path / "mvp-business.db")
    await init_database(database)
    await bootstrap_identity_store(database)
    vector_store = VectorStoreStub()
    task_graph = TaskGraph(database)
    scheduler = SchedulerStub()

    app = FastAPI()
    install_error_handlers(app)
    app.state.db_client = database
    app.state.vector_store = vector_store
    app.state.task_graph = task_graph
    app.state.scheduler = scheduler
    app.include_router(auth_router, prefix="/auth")
    app.include_router(channels_router, prefix="/channels")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(management_router, prefix="/admin")
    app.include_router(workflows_router, prefix="/admin")
    app.include_router(knowledge_router, prefix="/admin")
    app.include_router(watcher_router, prefix="/admin")
    app.include_router(sessions_router, prefix="/sessions")
    app.include_router(skills_router, prefix="/skills")
    return app, database, vector_store, scheduler


async def login(client, username, password):
    response = await client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_user(client, admin_headers, *, username, role, venue_id="venue-alpha"):
    response = await client.post(
        "/admin/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": "Strong-Password-2026",
            "display_name": username,
            "role": role,
            "venue_id": venue_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


async def create_in_review_sop(client, admin_headers):
    created = await client.post(
        "/admin/sops",
        headers=admin_headers,
        json={
            "title": "索道雷暴停运 SOP",
            "content": "收到雷暴预警后停止售票，疏散候车区游客，完成设备断电和现场复核。",
            "category": "极端天气",
            "priority": 1,
        },
    )
    assert created.status_code == 201, created.text
    sop_id = created.json()["sop"]["id"]
    submitted = await client.post(f"/admin/sops/{sop_id}/submit", headers=admin_headers)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["sop"]["status"] == "IN_REVIEW"
    return sop_id


async def create_controlled_action_context(
    database,
    *,
    session_id,
    user_id,
    event_id,
    task_id,
):
    now = time.time()
    await database.execute(
        """
        INSERT INTO sessions (session_id, user_id, venue_id, stage, created_at, updated_at)
        VALUES (?, ?, 'venue-alpha', 'active', ?, ?)
        """,
        (session_id, user_id, now, now),
    )
    await database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, push_id, from_user, raw_text, event_type,
            severity, context_trigger_data, memory_content, created_at,
            confirmed_at, venue_id, source_type, status, trace_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, '运营处置', 'P2', '{}', ?, ?, ?,
                  'venue-alpha', 'LIVE', 'OPEN', ?, ?)
        """,
        (
            event_id,
            f"SJ-{event_id.upper()}",
            f"message-{event_id}",
            user_id,
            "受控通知动作关联事件",
            "受控通知动作关联事件",
            now,
            now,
            f"trace-{event_id}",
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO tasks (
            id, business_id, venue_id, session_id, event_id, description,
            status, dependencies, result_schema_json, evidence_refs_json,
            assigned_user_id, created_at, updated_at
        ) VALUES (?, ?, 'venue-alpha', ?, ?, ?, 'DONE', '[]', '{}', '[]', ?, ?, ?)
        """,
        (
            task_id,
            f"RW-{task_id.upper()}",
            session_id,
            event_id,
            "完成现场复核并发起受控通知",
            user_id,
            now,
            now,
        ),
    )


@pytest.mark.asyncio
async def test_management_api_enforces_roles_and_records_changes(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        venue = await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-beta", "name": "南麓游客中心"},
        )
        assert venue.status_code == 201

        manager = await create_user(client, admin_headers, username="manager-a", role="manager")
        operator = await create_user(client, admin_headers, username="operator-a", role="operator")
        await create_user(client, admin_headers, username="operator-b", role="operator", venue_id="venue-beta")
        manager_headers = await login(client, "manager-a", "Strong-Password-2026")
        operator_headers = await login(client, "operator-a", "Strong-Password-2026")

        assignees = await client.get("/admin/assignees", headers=manager_headers)
        assert assignees.status_code == 200, assignees.text
        assert {item["id"] for item in assignees.json()["assignees"]} == {manager["id"], operator["id"]}
        assert all(item["venue_id"] == "venue-alpha" for item in assignees.json()["assignees"])

        assignees_forbidden = await client.get("/admin/assignees", headers=operator_headers)
        assert assignees_forbidden.status_code == 403

        forbidden = await client.post(
            "/admin/users",
            headers=manager_headers,
            json={
                "username": "forbidden-user",
                "password": "Strong-Password-2026",
                "display_name": "无权创建",
                "role": "operator",
                "venue_id": "venue-alpha",
            },
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "AUTH_FORBIDDEN"

        updated = await client.put(
            "/admin/settings/sla_p0_minutes",
            headers=admin_headers,
            json={"value": 8},
        )
        assert updated.status_code == 200
        assert updated.json()["value"] == 8

        invalid = await client.put(
            "/admin/settings/sla_p0_minutes",
            headers=admin_headers,
            json={"value": 0},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "SETTING_VALUE_INVALID"

        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-a-real-secret")
        integrations = await client.get("/admin/integrations", headers=manager_headers)
        deepseek = next(item for item in integrations.json()["integrations"] if item["id"] == "deepseek")
        assert deepseek["status"] == "BLOCKED"
        assert deepseek["configured"] is True
        assert deepseek["live_verified"] is False
        assert deepseek["model"] == "deepseek-v4-flash"
        assert "test-key-not-a-real-secret" not in integrations.text

        await database.execute(
            """
            INSERT INTO llm_call_logs (
                id, venue_id, trace_id, provider, model_name, status,
                attempt_count, latency_seconds, total_tokens, request_id,
                is_mock, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "llm-integration-live-1",
                "venue-alpha",
                "trace-integration-live-1",
                "deepseek",
                "deepseek-v4-flash",
                "SUCCEEDED",
                1,
                0.8,
                42,
                "request-live-1",
                0,
                time.time(),
            ),
        )
        verified_integrations = await client.get("/admin/integrations", headers=manager_headers)
        verified_deepseek = next(
            item for item in verified_integrations.json()["integrations"] if item["id"] == "deepseek"
        )
        assert verified_deepseek["status"] == "READY"
        assert verified_deepseek["live_verified"] is True
        assert verified_deepseek["evidence"]["request_id"] == "request-live-1"

        audit = await client.get("/admin/audit-logs", headers=manager_headers)
        actions = {row["action"] for row in audit.json()["audit_logs"]}
        assert {"VENUE_CREATED", "USER_CREATED", "SETTING_UPDATED"} <= actions
        assert manager["venue_id"] == "venue-alpha"

    await database.close()


@pytest.mark.asyncio
async def test_real_wecom_stays_policy_disabled_despite_credentials_and_legacy_delivery_evidence(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    for key, value in {
        "WECHAT_TOKEN": "test-token",
        "WECHAT_ENCODING_AES_KEY": "a" * 43,
        "WECHAT_CORP_ID": "corp-alpha",
        "WECHAT_CORP_SECRET": "test-corp-secret",
        "WECHAT_AGENT_ID": "1000002",
    }.items():
        monkeypatch.setenv(key, value)
    now = time.time()
    await database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, channel, external_message_id, external_conversation_id,
            reply_text, delivery_status, delivered_at, created_at, updated_at,
            processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', 'WECOM', ?, ?, ?,
                  'DELIVERED', ?, ?, ?, ?)
        """,
        (
            "wecom-live-message-001",
            "trace-wecom-live-001",
            "wecom-live-session-001",
            "operator-wecom-live",
            "venue-alpha",
            "东门扶梯停运",
            "external-wecom-live-001",
            "corp-alpha:operator-wecom-live",
            "已受理并回复",
            now,
            now - 2,
            now,
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO push_logs (
            push_id, venue_id, msg_id, from_user, raw_text, pushed_at,
            adoption_status, trace_id, channel, recipient, delivery_status,
            idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, 'not_applicable', ?, 'WECOM_REPLY', ?,
                  'DELIVERED', ?)
        """,
        (
            "wecom-reply-ledger-001",
            "venue-alpha",
            "wecom-live-message-001",
            "operator-wecom-live",
            "已受理并回复",
            now,
            "trace-wecom-live-001",
            "operator-wecom-live",
            "assistant-reply:wecom-live-message-001",
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
            response = await client.get("/admin/integrations", headers=admin_headers)

        assert response.status_code == 200, response.text
        wechat = next(
            item for item in response.json()["integrations"] if item["id"] == "wechat"
        )
        simulator = next(
            item for item in response.json()["integrations"] if item["id"] == "wecom_simulator"
        )
        assert simulator["status"] == "SIMULATOR_READY"
        assert simulator["evidence"]["entrypoint"] == "/simulator/wecom/"
        assert simulator["evidence"]["real_wecom_enabled"] is False
        assert wechat["status"] == "DISABLED_BY_POLICY"
        assert wechat["configured"] is False
        assert wechat["live_verified"] is False
        assert wechat["safe_disabled_verified"] is True
        assert wechat["evidence"] == {
            "policy_mode": "WECOM_SIMULATOR_ONLY",
            "real_wecom_enabled": False,
        }
        assert "仅允许企业内部系统接入环境" in wechat["blocked_reason"]
        assert "test-corp-secret" not in response.text
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_user_master_data_preserves_department_and_job_title(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/users",
            headers=admin_headers,
            json={
                "username": "equipment-expert",
                "password": "Strong-Password-2026",
                "display_name": "张建国",
                "role": "operator",
                "venue_id": "venue-alpha",
                "department": "设备运营部",
                "job_title": "资深设备主管",
            },
        )

        assert created.status_code == 201, created.text
        user = created.json()["user"]
        assert user["department"] == "设备运营部"
        assert user["job_title"] == "资深设备主管"

        updated = await client.patch(
            f"/admin/users/{user['id']}",
            headers=admin_headers,
            json={"department": "运营保障部", "job_title": "设备专家"},
        )
        listed = await client.get(
            "/admin/users",
            headers=admin_headers,
            params={"venue_id": "venue-alpha"},
        )

    assert updated.status_code == 200, updated.text
    assert updated.json()["user"]["department"] == "运营保障部"
    assert updated.json()["user"]["job_title"] == "设备专家"
    listed_user = next(item for item in listed.json()["users"] if item["id"] == user["id"])
    assert listed_user["department"] == "运营保障部"
    assert listed_user["job_title"] == "设备专家"
    await database.close()


@pytest.mark.asyncio
async def test_uat_baseline_rejects_sqlite_test_backend(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        operator = await create_user(
            client,
            admin_headers,
            username="uat-operator",
            role="operator",
        )
        mapped = await client.post(
            "/channels/identities",
            headers=admin_headers,
            json={
                "channel": "WECOM_SIMULATOR",
                "external_tenant_id": "simulator-tenant-alpha",
                "external_user_id": "simulator-uat-operator",
                "user_id": operator["id"],
            },
        )
        assert mapped.status_code == 201, mapped.text
        snapshot = await client.get("/admin/uat-baseline", headers=admin_headers)

    assert snapshot.status_code == 503, snapshot.text
    assert snapshot.json()["detail"]["code"] == "UAT_POSTGRESQL_REQUIRED"
    assert "password_hash" not in snapshot.text
    assert "Mvp-Admin-Password-2026" not in snapshot.text
    await database.close()


def test_integration_evidence_query_uses_portable_boolean_sql():
    source = (Path(__file__).parents[2] / "src" / "memory_palace" / "api" / "v1" / "endpoints" / "management.py").read_text(encoding="utf-8")

    assert "NOT COALESCE(is_mock, FALSE)" in source
    assert "COALESCE(is_mock, 0)" not in source


@pytest.mark.asyncio
async def test_feature_registry_is_visible_to_management_roles_only(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        await create_user(client, admin_headers, username="registry-manager", role="manager")
        await create_user(client, admin_headers, username="registry-operator", role="operator")
        manager_headers = await login(client, "registry-manager", "Strong-Password-2026")
        operator_headers = await login(client, "registry-operator", "Strong-Password-2026")

        for headers in (admin_headers, manager_headers):
            response = await client.get("/admin/feature-registry", headers=headers)
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["summary"]["business_total"] == 20
            assert payload["summary"]["business_ready"] == 0
            assert payload["summary"]["release_gate_passed"] is False
            assert {journey["id"] for journey in payload["uat_journeys"]} == {
                *(f"E2E-{number:02d}" for number in range(17)),
                *(f"UAT-F{number:02d}" for number in range(1, 14)),
            }

        forbidden = await client.get("/admin/feature-registry", headers=operator_headers)
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "AUTH_FORBIDDEN"

    await database.close()


@pytest.mark.asyncio
async def test_feature_registry_consumes_current_tenant_runtime_evidence(tmp_path, monkeypatch):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "from_user": "operator-runtime-evidence",
                "raw_text": "东门闸机断电，已人工补录并同步知识索引。",
                "event_type": "设施故障",
                "severity": "P1",
            },
        )
        assert created.status_code == 200, created.text
        event_id = created.json()["event_id"]
        event_vector = vector_store.documents[f"evt_{event_id}"]
        assert event_vector["metadata"]["title"] == "设施故障事件"
        assert event_vector["metadata"]["source_type"] == "HISTORY"
        assert event_vector["metadata"]["source_id"] == event_id
        assert event_vector["metadata"]["version"] == 1

        response = await client.get("/admin/feature-registry", headers=admin_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        items = {item["id"]: item for item in payload["items"]}

        assert items["MVP-BIZ-004"]["status"] == "BLOCKED"
        assert items["MVP-BIZ-005"]["status"] == "BLOCKED"
        required_delivery_evidence = {"浏览器验收证据", "Live 验收证据", "UAT 验收证据"}
        assert set(items["MVP-BIZ-004"]["acceptance"]["missing"]) == required_delivery_evidence
        assert set(items["MVP-BIZ-005"]["acceptance"]["missing"]) == required_delivery_evidence
        assert "历史事件已持久化" in items["MVP-BIZ-004"]["acceptance"]["satisfied"]
        assert "事件补录成功审计" in items["MVP-BIZ-004"]["acceptance"]["satisfied"]
        assert "向量库健康" in items["MVP-BIZ-004"]["acceptance"]["satisfied"]
        assert "事件列表与详情存在真实数据" in items["MVP-BIZ-005"]["acceptance"]["satisfied"]
        assert "事件来源审计" in items["MVP-BIZ-005"]["acceptance"]["satisfied"]
        assert items["MVP-BIZ-006"]["status"] == "BLOCKED"
        assert set(items["MVP-BIZ-006"]["acceptance"]["missing"]) == required_delivery_evidence | {
            "事件已完成闭环",
            "事件处置更新审计",
            "闭环门禁拒绝审计",
            "事件闭环审计",
            "闭环经验候选创建审计",
        }
        assert created.json()["trace_id"] in {
            record.get("trace_id") for record in items["MVP-BIZ-004"]["runtime_evidence"]
        }

    await database.close()



@pytest.mark.asyncio
async def test_feature_registry_accepts_distinct_live_trace_per_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    now = time.time()
    agent_ids = (
        "ContextTrigger",
        "Router",
        "Commander",
        "MemoryOps",
        "Persona",
        "PersonaExtract",
        "TodoWrite",
        "Watcher",
    )
    for index, agent_id in enumerate(agent_ids):
        await database.execute(
            """
            INSERT INTO llm_call_logs (
                id, venue_id, trace_id, agent_id, agent_name, provider, model_name, status,
                attempt_count, latency_seconds, total_tokens, request_id, is_mock, created_at
            ) VALUES (?, ?, ?, ?, ?, 'deepseek', 'deepseek-v4-flash', 'SUCCEEDED', ?, ?, ?, ?, 0, ?)
            """,
            (
                f"llm-agent-{index}",
                "venue-alpha",
                f"trace-agent-{index}",
                agent_id,
                agent_id,
                1,
                0.2 + index / 100,
                20 + index,
                f"request-agent-{index}",
                now + index,
            ),
        )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.get("/admin/feature-registry", headers=admin_headers)

    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in response.json()["items"]}
    for index, agent_id in enumerate(agent_ids):
        evidence = [
            record
            for record in items[agent_id]["runtime_evidence"]
            if record.get("kind") == "agent_trace"
        ]
        assert evidence
        assert evidence[0]["agent_id"] == agent_id
        assert evidence[0]["trace_id"] == f"trace-agent-{index}"
        assert evidence[0]["status"] == "SUCCEEDED"
        assert evidence[0]["is_mock"] is False

    await database.close()

@pytest.mark.asyncio
async def test_feature_registry_accepts_completed_message_agent_chain_from_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    trace_id = "trace-message-agent-chain"
    now = time.time()
    await database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, target_agent, result_json, created_at, updated_at, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', 'commander', ?, ?, ?, ?)
        """,
        (
            "message-agent-chain",
            trace_id,
            "session-agent-chain",
            "user-admin",
            "venue-alpha",
            "Emergency message handled by the full agent chain.",
            json.dumps(
                {
                    "route": {
                        "target_agent": "commander",
                        "router_confidence": 0.98,
                        "context_trigger_data": {"should_trigger": True},
                    }
                }
            ),
            now,
            now,
            now,
        ),
    )
    for index, agent_id in enumerate(("ContextTrigger", "Router", "Commander", "MemoryOps")):
        await database.execute(
            """
            INSERT INTO llm_call_logs (
                id, venue_id, trace_id, agent_id, agent_name, provider, model_name, status,
                attempt_count, latency_seconds, total_tokens, request_id, is_mock, created_at
            ) VALUES (?, 'venue-alpha', ?, ?, ?, 'deepseek', 'deepseek-v4-flash',
                      'SUCCEEDED', 1, 0.2, 20, ?, 0, ?)
            """,
            (
                f"llm-message-chain-{index}",
                trace_id,
                agent_id,
                agent_id,
                f"request-message-chain-{index}",
                now + index,
            ),
        )
    for index, agent_id in enumerate(("ContextTrigger", "Router", "Commander", "MemoryOps")):
        await database.execute(
            """
            INSERT INTO llm_call_logs (
                id, venue_id, trace_id, agent_id, agent_name, provider, model_name, status,
                attempt_count, latency_seconds, total_tokens, request_id, is_mock, created_at
            ) VALUES (?, 'venue-alpha', ?, ?, ?, 'deepseek', 'deepseek-v4-flash',
                      'SUCCEEDED', 1, 0.2, 20, ?, 0, ?)
            """,
            (
                f"llm-newer-unrelated-{index}",
                f"trace-newer-unrelated-{index}",
                agent_id,
                agent_id,
                f"request-newer-unrelated-{index}",
                now + 100 + index,
            ),
        )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.get("/admin/feature-registry", headers=admin_headers)

    assert response.status_code == 200, response.text
    message_intake = next(
        item for item in response.json()["items"] if item["id"] == "MVP-BIZ-003"
    )
    chain = next(
        record
        for record in message_intake["runtime_evidence"]
        if record.get("kind") == "message_agent_chain"
    )
    assert chain["trace_id"] == trace_id
    assert chain["agents"] == ["ContextTrigger", "Router", "Commander", "MemoryOps"]

    await database.close()


@pytest.mark.asyncio
async def test_task_state_machine_and_tenant_boundaries_are_real(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        operator = await create_user(client, admin_headers, username="operator-a", role="operator")
        other_operator = await create_user(client, admin_headers, username="operator-other", role="operator")
        operator_headers = await login(client, "operator-a", "Strong-Password-2026")
        other_headers = await login(client, "operator-other", "Strong-Password-2026")

        created = await client.post(
            "/admin/tasks",
            headers=admin_headers,
            json={
                "session_id": "session-incident-1",
                "description": "核验东门疏散通道并反馈现场照片",
                "assigned_user_id": operator["id"],
                "assigned_agent": "commander",
                "max_attempts": 1,
            },
        )
        assert created.status_code == 201
        task_id = created.json()["task"]["id"]

        forbidden = await client.post(f"/admin/tasks/{task_id}/start", headers=other_headers)
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "TASK_NOT_ASSIGNED"

        started = await client.post(f"/admin/tasks/{task_id}/start", headers=operator_headers)
        assert started.status_code == 200
        assert started.json()["task"]["status"] == "RUNNING"

        failed = await client.post(
            f"/admin/tasks/{task_id}/fail",
            headers=operator_headers,
            json={"error": "现场网络中断，照片上传失败"},
        )
        assert failed.status_code == 200
        assert failed.json()["task"]["status"] == "FAILED"
        assert failed.json()["task"]["attempts"] == 1
        assert failed.json()["task"]["error"]

        retried = await client.post(f"/admin/tasks/{task_id}/retry", headers=admin_headers)
        assert retried.status_code == 200
        assert retried.json()["task"]["status"] == "PENDING"
        assert retried.json()["task"]["attempts"] == 1
        assert retried.json()["task"]["max_attempts"] == 2

        restarted = await client.post(f"/admin/tasks/{task_id}/start", headers=operator_headers)
        assert restarted.json()["task"]["attempts"] == 2
        assert restarted.json()["task"]["max_attempts"] == 2
        completed = await client.post(
            f"/admin/tasks/{task_id}/complete",
            headers=operator_headers,
            json={"result": {"summary": "通道已恢复畅通", "photo_count": 2}},
        )
        assert completed.status_code == 200
        assert completed.json()["task"]["status"] == "DONE"

        audit = await client.get("/admin/audit-logs", headers=admin_headers)
        audit_rows = audit.json()["audit_logs"]
        actions = {row["action"] for row in audit_rows}
        assert {"TASK_CREATED", "TASK_STARTED", "TASK_FAILED", "TASK_RETRIED", "TASK_COMPLETED"} <= actions
        failed_audit = next(row for row in audit_rows if row["action"] == "TASK_FAILED" and row["resource_id"] == task_id)
        assert failed_audit["metadata"]["attempts"] == 1
        assert failed_audit["metadata"]["will_retry"] is False
        assert failed_audit["metadata"]["error"]

    await database.close()


@pytest.mark.asyncio
async def test_approval_detail_is_loaded_from_persistent_database(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    await database.execute(
        """
        INSERT INTO approval_requests (
            approval_id, tool_name, args, session_id, user_id, requested_at,
            requested_by, status, venue_id, reviewed_at, reviewed_by, comment,
            execution_result, execution_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "approval-history-1",
            "send_notification",
            json.dumps({"channel": "wechat", "recipient": "team-east"}),
            "session-history-1",
            "operator-history-1",
            time.time() - 600,
            "commander",
            "APPROVED",
            "venue-alpha",
            time.time() - 500,
            "admin-history-1",
            "同意执行",
            json.dumps({"delivery_id": "delivery-1"}),
            None,
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        detail = await client.get("/admin/approvals/approval-history-1", headers=admin_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "APPROVED"
        assert detail.json()["execution_result"] == {"delivery_id": "delivery-1"}

        missing = await client.get("/admin/approvals/missing", headers=admin_headers)
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "APPROVAL_NOT_FOUND"

    await database.close()


@pytest.mark.asyncio
async def test_disabled_notification_action_creates_no_approval_or_audit(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.memory_palace.api.v1.endpoints.admin.notification_action_readiness",
        lambda *_: {
            "available": False,
            "channels": ["sms"],
            "missing": ["SMS_PROVIDER_ADAPTER"],
        },
    )
    await create_controlled_action_context(
        database,
        session_id="session-disabled-action",
        user_id="operator-disabled",
        event_id="event-disabled-action",
        task_id="task-disabled-action",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.post(
            "/admin/action-requests",
            headers=admin_headers,
            json={
                "tool_name": "send_sms",
                "session_id": "session-disabled-action",
                "event_id": "event-disabled-action",
                "task_id": "task-disabled-action",
                "recipient": "13800138000",
                "message": "Controlled notification must remain disabled",
                "priority": "high",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INTEGRATION_DISABLED"
    approvals = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM approval_requests WHERE venue_id = ?",
        ("venue-alpha",),
    )
    audits = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE venue_id = ? AND action = ?",
        ("venue-alpha", "CONTROLLED_ACTION_REQUESTED"),
    )
    assert approvals["total"] == 0
    assert audits["total"] == 0
    await database.close()


@pytest.mark.asyncio
async def test_in_app_alert_completes_approval_delivery_and_adoption_chain(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    from src.memory_palace.core.permissions import get_permission_engine

    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    monkeypatch.setattr(engine, "_db", database)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        manager = await create_user(client, admin_headers, username="alert-manager", role="manager")
        manager_headers = await login(client, "alert-manager", "Strong-Password-2026")
        await create_controlled_action_context(
            database,
            session_id="session-in-app-alert",
            user_id=manager["id"],
            event_id="event-in-app-alert",
            task_id="task-in-app-alert",
        )

        requested = await client.post(
            "/admin/action-requests",
            headers=manager_headers,
            json={
                "tool_name": "send_in_app_alert",
                "session_id": "session-in-app-alert",
                "event_id": "event-in-app-alert",
                "task_id": "task-in-app-alert",
                "message": "东门客流达到黄色预警阈值，请现场复核。",
                "priority": "warning",
            },
        )
        assert requested.status_code == 202, requested.text
        approval_id = requested.json()["approval_id"]

        approved = await client.post(
            f"/admin/approvals/{approval_id}/approve",
            headers=admin_headers,
            json={"comment": "批准发送站内告警"},
        )
        assert approved.status_code == 200, approved.text
        approval_result = approved.json()
        assert approval_result["execution_result"]["status"] == "executed"
        delivery = approval_result["execution_result"]["result"]
        assert delivery["status"] == "DELIVERED"
        assert delivery["channel"] == "in_app"
        assert delivery["recipient"] == "session:session-in-app-alert"

        push_row = await database.fetch_one(
            "SELECT * FROM push_logs WHERE push_id = ? AND venue_id = ?",
            (delivery["push_id"], "venue-alpha"),
        )
        assert push_row["channel"] == "in_app"
        assert push_row["recipient"] == "session:session-in-app-alert"
        assert push_row["delivery_status"] == "DELIVERED"
        assert push_row["trace_id"] == approval_result["trace_id"]

        integrations = await client.get("/admin/integrations", headers=manager_headers)
        assert integrations.status_code == 200, integrations.text
        in_app = next(
            item for item in integrations.json()["integrations"] if item["id"] == "in_app"
        )
        assert in_app["status"] == "READY"
        assert in_app["configured"] is True
        assert in_app["live_verified"] is True
        assert in_app["evidence"]["push_id"] == delivery["push_id"]

        invocation = await database.fetch_one(
            """
            SELECT * FROM tool_invocation_logs
            WHERE venue_id = ? AND tool_name = ? AND session_id = ?
            """,
            ("venue-alpha", "send_in_app_alert", "session-in-app-alert"),
        )
        assert invocation is not None
        assert invocation["user_id"] == manager["id"]

        adopted = await client.patch(
            f"/admin/push_logs/{delivery['push_id']}/adoption",
            headers=manager_headers,
            json={"status": "adopted", "notes": "现场已确认并执行分流"},
        )
        assert adopted.status_code == 200, adopted.text
        reviewed = await database.fetch_one(
            "SELECT adoption_status, confirmed_by FROM push_logs WHERE push_id = ?",
            (delivery["push_id"],),
        )
        assert reviewed["adoption_status"] == "adopted"
        assert reviewed["confirmed_by"] == manager["id"]

        audit = await client.get("/admin/audit-logs", headers=manager_headers)
        action_names = {row["action"] for row in audit.json()["audit_logs"]}
        assert {
            "CONTROLLED_ACTION_REQUESTED",
            "APPROVAL_APPROVED",
            "CONTROLLED_ACTION_EXECUTED",
            "PUSH_ADOPTION_UPDATED",
        } <= action_names

    await database.close()


@pytest.mark.asyncio
async def test_controlled_action_preserves_business_trace_across_approval(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    from src.memory_palace.core.permissions import get_permission_engine

    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    monkeypatch.setattr(engine, "_db", database)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        manager = await create_user(client, admin_headers, username="trace-manager", role="manager")
        manager_headers = await login(client, "trace-manager", "Strong-Password-2026")
        await create_controlled_action_context(
            database,
            session_id="session-business-trace",
            user_id=manager["id"],
            event_id="event-business-trace",
            task_id="task-business-trace",
        )

        business_trace_id = "trace-controlled-business-001"
        requested = await client.post(
            "/admin/action-requests",
            headers={**manager_headers, "X-Trace-ID": business_trace_id},
            json={
                "tool_name": "send_in_app_alert",
                "session_id": "session-business-trace",
                "event_id": "event-business-trace",
                "task_id": "task-business-trace",
                "message": "东门客流达到黄色预警阈值，请现场复核。",
                "priority": "warning",
            },
        )
        assert requested.status_code == 202, requested.text
        assert requested.json()["trace_id"] == business_trace_id
        approval_id = requested.json()["approval_id"]

        detail = await client.get(f"/admin/approvals/{approval_id}", headers=manager_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["correlation_trace_id"] == business_trace_id

        approved = await client.post(
            f"/admin/approvals/{approval_id}/approve",
            headers={**admin_headers, "X-Trace-ID": "trace-review-http-request"},
            json={"comment": "批准发送站内告警"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["trace_id"] == business_trace_id

        timeline = await client.get(f"/admin/traces/{business_trace_id}", headers=manager_headers)
        assert timeline.status_code == 200, timeline.text
        payload = timeline.json()
        assert payload["summary"]["approvals"] == 1
        assert payload["summary"]["tool_invocations"] == 1
        assert payload["summary"]["push_logs"] == 1
        assert {
            (item["kind"], item["resource_id"])
            for item in payload["timeline"]
            if item["kind"] in {"APPROVAL", "PUSH"}
        } == {
            ("APPROVAL", approval_id),
            ("PUSH", approved.json()["execution_result"]["result"]["push_id"]),
        }

    await database.close()


@pytest.mark.asyncio
async def test_trace_timeline_does_not_mix_controlled_actions_from_same_session(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    from src.memory_palace.core.permissions import get_permission_engine

    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    monkeypatch.setattr(engine, "_db", database)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        manager = await create_user(client, admin_headers, username="timeline-manager", role="manager")
        manager_headers = await login(client, "timeline-manager", "Strong-Password-2026")
        now = time.time()
        session_id = "session-shared-by-two-traces"
        await create_controlled_action_context(
            database,
            session_id=session_id,
            user_id=manager["id"],
            event_id="event-shared-by-two-traces",
            task_id="task-shared-by-two-traces",
        )

        approval_ids = []
        for index, trace_id in enumerate(("trace-action-alpha", "trace-action-beta"), start=1):
            requested = await client.post(
                "/admin/action-requests",
                headers={**manager_headers, "X-Trace-ID": trace_id},
                json={
                    "tool_name": "send_in_app_alert",
                    "session_id": session_id,
                    "event_id": "event-shared-by-two-traces",
                    "task_id": "task-shared-by-two-traces",
                    "message": f"第 {index} 条独立站内告警",
                    "priority": "warning",
                },
            )
            assert requested.status_code == 202, requested.text
            approval_ids.append(requested.json()["approval_id"])

        for approval_id in approval_ids:
            approved = await client.post(
                f"/admin/approvals/{approval_id}/approve",
                headers=admin_headers,
                json={"comment": "批准独立告警"},
            )
            assert approved.status_code == 200, approved.text

        await database.execute(
            """
            INSERT INTO message_runs (
                message_id, trace_id, session_id, user_id, venue_id, content,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "message-action-alpha",
                "trace-action-alpha",
                session_id,
                manager["id"],
                "venue-alpha",
                "第一条业务 Trace 的来源消息",
                "COMPLETED",
                now,
                now,
            ),
        )

        response = await client.get("/admin/traces/trace-action-alpha", headers=manager_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["summary"]["approvals"] == 1
        assert payload["summary"]["tool_invocations"] == 1
        assert {
            item["resource_id"] for item in payload["timeline"] if item["kind"] == "APPROVAL"
        } == {approval_ids[0]}
        assert {
            item["resource_id"] for item in payload["timeline"] if item["kind"] == "TOOL"
        } == {approval_ids[0]}

    await database.close()


@pytest.mark.asyncio
async def test_controlled_action_uses_real_permission_approval_and_audit_chain(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    from src.memory_palace.core.permissions import get_permission_engine
    from src.memory_palace.tools import tool_executor

    engine = get_permission_engine()
    monkeypatch.setattr(engine, "_pending_approvals", {})
    monkeypatch.setattr(engine, "_cooldown_cache", {})
    monkeypatch.setattr(engine, "_db", database)
    delivered = []

    async def provider_backed_sms(phone, message, priority="normal"):
        delivered.append({"phone": phone, "message": message, "priority": priority})
        return {"status": "DELIVERED", "provider_id": "sandbox-receipt-1"}

    monkeypatch.setitem(tool_executor._tools, "send_sms", provider_backed_sms)
    monkeypatch.setattr(
        "src.memory_palace.api.v1.endpoints.admin.notification_action_readiness",
        lambda *_: {"available": True, "channels": ["sms"], "missing": []},
    )


    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        manager = await create_user(client, admin_headers, username="action-manager", role="manager")
        manager_headers = await login(client, "action-manager", "Strong-Password-2026")
        await create_controlled_action_context(
            database,
            session_id="session-controlled-action",
            user_id=manager["id"],
            event_id="event-controlled-action",
            task_id="task-controlled-action",
        )

        rejected_request = await client.post(
            "/admin/action-requests",
            headers=manager_headers,
            json={
                "tool_name": "send_sms",
                "session_id": "session-controlled-action",
                "event_id": "event-controlled-action",
                "task_id": "task-controlled-action",
                "recipient": "13800138000",
                "message": "索道入口暂停放行",
                "priority": "high",
            },
        )
        assert rejected_request.status_code == 202, rejected_request.text
        rejected_id = rejected_request.json()["approval_id"]
        assert rejected_request.json()["status"] == "pending_approval"
        requested_audit = await database.fetch_one(
            """
            SELECT outcome, metadata_json FROM audit_logs
            WHERE venue_id = ? AND action = ? AND resource_id = ?
            """,
            ("venue-alpha", "CONTROLLED_ACTION_REQUESTED", rejected_id),
        )
        assert requested_audit["outcome"] == "SUCCEEDED"
        requested_metadata = (
            json.loads(requested_audit["metadata_json"])
            if isinstance(requested_audit["metadata_json"], str)
            else requested_audit["metadata_json"]
        )
        assert requested_metadata["approval_status"] == "PENDING"

        rejected = await client.post(
            f"/admin/approvals/{rejected_id}/reject",
            headers=admin_headers,
            json={"comment": "现场复核后无需发送"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["trace_id"] == rejected_request.json()["trace_id"]
        assert delivered == []

        approved_request = await client.post(
            "/admin/action-requests",
            headers=manager_headers,
            json={
                "tool_name": "send_sms",
                "session_id": "session-controlled-action",
                "event_id": "event-controlled-action",
                "task_id": "task-controlled-action",
                "recipient": "13800138001",
                "message": "索道入口执行临时管控",
                "priority": "normal",
            },
        )
        assert approved_request.status_code == 202, approved_request.text
        approved_id = approved_request.json()["approval_id"]

        approved = await client.post(
            f"/admin/approvals/{approved_id}/approve",
            headers=admin_headers,
            json={"comment": "批准执行"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["trace_id"] == approved_request.json()["trace_id"]
        assert approved.json()["execution_result"]["status"] == "executed"
        assert approved.json()["execution_result"]["result"]["provider_id"] == "sandbox-receipt-1"
        assert delivered == [
            {"phone": "13800138001", "message": "索道入口执行临时管控", "priority": "normal"}
        ]

        actions = await client.get("/admin/approvals?status=ALL", headers=manager_headers)
        assert actions.status_code == 200, actions.text
        records = {item["approval_id"]: item for item in actions.json()}
        assert records[rejected_id]["status"] == "REJECTED"
        assert records[approved_id]["status"] == "APPROVED"
        assert records[approved_id]["execution_result"]["status"] == "executed"

        audit = await client.get("/admin/audit-logs", headers=manager_headers)
        action_names = {row["action"] for row in audit.json()["audit_logs"]}
        assert {
            "CONTROLLED_ACTION_REQUESTED",
            "APPROVAL_REJECTED",
            "APPROVAL_APPROVED",
            "CONTROLLED_ACTION_EXECUTED",
        } <= action_names

    await database.close()


@pytest.mark.asyncio
async def test_admin_queue_diagnostics_and_dead_letter_retry_are_audited(tmp_path, monkeypatch):
    class QueueStub:
        def __init__(self):
            self.retried = []

        async def diagnostics(self):
            return {
                "backend": "redis_streams",
                "connected": True,
                "stream": "memory_palace:messages",
                "group": "mp_workers",
                "stream_depth": 9,
                "pending": 2,
                "lag": 4,
                "consumers": [{"name": "worker_1", "pending": 2, "idle_ms": 80}],
                "dead_letter_stream": "memory_palace:dead_letter",
                "dead_letter_depth": 2,
            }

        async def list_dead_letters(self, limit=20):
            return [
                {
                    "id": "1700000000500-0",
                    "created_at_ms": 1700000000500,
                    "message": {"msg_id": "message-7", "venue_id": "venue-alpha"},
                    "error": "模型连续超时",
                    "retries": 3,
                },
                {
                    "id": "1700000000600-0",
                    "created_at_ms": 1700000000600,
                    "message": {"msg_id": "message-other", "venue_id": "venue-beta"},
                    "error": "渠道不可用",
                    "retries": 3,
                },
            ][:limit]

        async def retry_dead_letter(self, dead_letter_id):
            self.retried.append(dead_letter_id)
            return {
                "dead_letter_id": dead_letter_id,
                "stream_message_id": "1700000000800-0",
                "message_id": "message-7",
            }

    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    queue = QueueStub()
    app.state.message_queue = queue
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")

        diagnostics = await client.get("/admin/queue", headers=admin_headers)
        assert diagnostics.status_code == 200, diagnostics.text
        assert diagnostics.json()["pending"] == 2
        assert diagnostics.json()["dead_letter_depth"] == 2

        dead_letters = await client.get("/admin/dead-letters", headers=admin_headers)
        assert dead_letters.status_code == 200, dead_letters.text
        assert [item["id"] for item in dead_letters.json()["dead_letters"]] == ["1700000000500-0"]

        retried = await client.post(
            "/admin/dead-letters/1700000000500-0/retry",
            headers=admin_headers,
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["stream_message_id"] == "1700000000800-0"
        assert queue.retried == ["1700000000500-0"]

        audit = await client.get("/admin/audit-logs", headers=admin_headers)
        assert "DEAD_LETTER_RETRIED" in {row["action"] for row in audit.json()["audit_logs"]}

    await database.close()


@pytest.mark.asyncio
async def test_admin_health_does_not_claim_unconfigured_deepseek_is_healthy(tmp_path, monkeypatch):
    class QueueStub:
        async def diagnostics(self):
            return {"connected": True, "pending": 0, "dead_letter_depth": 0}

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY_FILE", raising=False)
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.state.message_queue = QueueStub()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.get("/admin/health", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["db"] == "healthy"
    assert response.json()["components"]["queue"] == "healthy"
    assert response.json()["components"]["llm"] == "disabled_requires_config"
    await database.close()


@pytest.mark.asyncio
async def test_admin_health_requires_successful_live_llm_evidence_for_healthy(tmp_path, monkeypatch):
    class QueueStub:
        async def diagnostics(self):
            return {"connected": True, "pending": 0, "dead_letter_depth": 0}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-a-real-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.state.message_queue = QueueStub()
    await database.execute(
        """
        INSERT INTO llm_call_logs (
            id, venue_id, trace_id, provider, model_name, status,
            attempt_count, latency_seconds, total_tokens, request_id,
            is_mock, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "llm-health-1",
            "venue-alpha",
            "trace-health-1",
            "deepseek",
            "deepseek-v4-flash",
            "SUCCEEDED",
            1,
            0.82,
            128,
            "provider-request-1",
            False,
            time.time(),
        ),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.get("/admin/health", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "healthy"
    assert response.json()["components"]["llm"] == "healthy"
    await database.close()


@pytest.mark.asyncio
async def test_existing_enterprise_sop_keeps_requested_business_version_when_published(
    tmp_path,
    monkeypatch,
):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/sops",
            headers=admin_headers,
            json={
                "title": "观光车雨后复运与异常异响处置",
                "content": "雨后复运前先完成车辆断电、轮端温度和异味检查；存在发热、焦味或制动跑偏时禁止载客试车。",
                "category": "设备安全",
                "priority": 1,
                "version": "2.1",
            },
        )

        assert created.status_code == 201, created.text
        sop = created.json()["sop"]
        assert sop["version"] == "2.1"
        submitted = await client.post(
            f"/admin/sops/{sop['id']}/submit",
            headers=admin_headers,
        )
        published = await client.post(
            f"/admin/sops/{sop['id']}/publish",
            headers=admin_headers,
            json={"comment": "确认沿用企业现行版本"},
        )
        listed = await client.get("/admin/sops", headers=admin_headers)

    assert submitted.status_code == 200, submitted.text
    assert published.status_code == 200, published.text
    assert published.json()["sop"]["version"] == "2.1"
    listed_sop = next(item for item in listed.json()["sops"] if item["id"] == sop["id"])
    assert listed_sop["version"] == "2.1"
    vector_metadata = vector_store.documents[f"sop:venue-alpha:{sop['id']}"]["metadata"]
    assert vector_metadata["version"] == "2.1"
    assert vector_metadata["status"] == "PUBLISHED"
    assert vector_metadata["published_at"] == published.json()["sop"]["published_at"]
    assert vector_metadata["publisher_name"] == "交付管理员"
    await database.close()


@pytest.mark.asyncio
async def test_knowledge_sop_and_vector_lifecycle_are_connected(tmp_path, monkeypatch):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/knowledge",
            headers=admin_headers,
            json={
                "title": "东门客流过载处置经验",
                "content": "东门瞬时客流超过承载阈值时，先打开北侧备用通道并通知广播岗。",
                "category": "客流安全",
                "tags": ["东门", "疏散"],
            },
        )
        assert created.status_code == 201, created.text
        knowledge = created.json()["knowledge"]
        assert knowledge["version"] == 1
        assert knowledge["vector_doc_id"] in vector_store.documents

        searched = await client.post(
            "/admin/knowledge/search",
            headers=admin_headers,
            json={"query": "备用通道", "top_k": 5, "threshold": 0.5},
        )
        assert searched.status_code == 200
        assert searched.json()["results"][0]["metadata"]["venue_id"] == "venue-alpha"

        updated = await client.put(
            f"/admin/knowledge/{knowledge['id']}",
            headers=admin_headers,
            json={"content": "东门瞬时客流超过承载阈值时，打开北侧备用通道并启动三级广播疏导。"},
        )
        assert updated.status_code == 200
        assert updated.json()["knowledge"]["version"] == 2

        sop_created = await client.post(
            "/admin/sops",
            headers=admin_headers,
            json={
                "title": "极端客流疏导 SOP",
                "content": "确认客流阈值，开放备用通道，安排安保分流，十五分钟后复核。",
                "category": "客流安全",
                "priority": 1,
            },
        )
        assert sop_created.status_code == 201, sop_created.text
        sop_id = sop_created.json()["sop"]["id"]
        submitted = await client.post(f"/admin/sops/{sop_id}/submit", headers=admin_headers)
        assert submitted.json()["sop"]["status"] == "IN_REVIEW"
        published = await client.post(
            f"/admin/sops/{sop_id}/publish",
            headers=admin_headers,
            json={"comment": "审核通过"},
        )
        assert published.status_code == 200, published.text
        assert published.json()["sop"]["status"] == "PUBLISHED"
        assert f"sop:venue-alpha:{sop_id}" in vector_store.documents

        detail = await client.get(f"/admin/sops/{sop_id}", headers=admin_headers)
        statuses = {version["status"] for version in detail.json()["versions"]}
        assert {"DRAFT", "IN_REVIEW", "PUBLISHED"} <= statuses

        deleted = await client.delete(f"/admin/knowledge/{knowledge['id']}", headers=admin_headers)
        assert deleted.status_code == 200
        assert knowledge["vector_doc_id"] not in vector_store.documents

    await database.close()


@pytest.mark.asyncio
async def test_knowledge_delete_restores_vector_when_database_update_fails(tmp_path, monkeypatch):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/knowledge",
            headers=admin_headers,
            json={
                "title": "暴雨闭园处置经验",
                "content": "红色暴雨预警生效后，关闭玻璃栈道并逐区清场。",
                "category": "极端天气",
                "tags": ["暴雨", "闭园"],
            },
        )
        knowledge = created.json()["knowledge"]
        vector_doc_id = knowledge["vector_doc_id"]
        original_execute = database.execute

        async def fail_delete_update(sql, parameters=()):
            if "UPDATE knowledge_documents SET status = 'DELETED'" in sql:
                raise RuntimeError("simulated database failure")
            return await original_execute(sql, parameters)

        monkeypatch.setattr(database, "execute", fail_delete_update)
        deleted = await client.delete(
            f"/admin/knowledge/{knowledge['id']}",
            headers=admin_headers,
        )

    assert deleted.status_code == 500
    assert vector_doc_id in vector_store.documents
    assert vector_store.documents[vector_doc_id]["text"] == "红色暴雨预警生效后，关闭玻璃栈道并逐区清场。"
    await database.close()


@pytest.mark.asyncio
async def test_knowledge_import_removes_all_vectors_when_a_later_row_fails(tmp_path, monkeypatch):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    original_execute = database.execute
    insert_count = 0

    async def fail_second_knowledge_insert(sql, parameters=()):
        nonlocal insert_count
        if "INSERT INTO knowledge_documents" in sql:
            insert_count += 1
            if insert_count == 2:
                raise RuntimeError("simulated second-row failure")
        return await original_execute(sql, parameters)

    monkeypatch.setattr(database, "execute", fail_second_knowledge_insert)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        imported = await client.post(
            "/admin/knowledge/import",
            headers=admin_headers,
            json={
                "entries": [
                    {"title": "东门疏散经验", "content": "开放北侧备用通道并安排安保分流。"},
                    {"title": "西门检修经验", "content": "隔离故障闸机并引导游客改走人工通道。"},
                ]
            },
        )

    assert imported.status_code == 500
    assert vector_store.documents == {}
    remaining = await database.fetch_one("SELECT COUNT(*) AS count FROM knowledge_documents")
    assert remaining["count"] == 0
    await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["knowledge", "audit"])
async def test_sop_publish_compensates_all_stores_when_a_later_step_fails(
    tmp_path,
    monkeypatch,
    failure_stage,
):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        sop_id = await create_in_review_sop(client, admin_headers)
        original_execute = database.execute

        async def fail_publish_step(sql, parameters=()):
            if failure_stage == "knowledge" and "INSERT INTO knowledge_documents" in sql:
                raise RuntimeError("simulated knowledge persistence failure")
            if (
                failure_stage == "audit"
                and "INSERT INTO audit_logs" in sql
                and len(parameters) > 2
                and parameters[2] == "SOP_PUBLISHED"
            ):
                raise RuntimeError("simulated publish audit failure")
            return await original_execute(sql, parameters)

        monkeypatch.setattr(database, "execute", fail_publish_step)
        published = await client.post(
            f"/admin/sops/{sop_id}/publish",
            headers=admin_headers,
            json={"comment": "审核通过"},
        )

    assert published.status_code == 500
    sop = await database.fetch_one("SELECT * FROM sop_documents WHERE id = ?", (sop_id,))
    assert sop["status"] == "IN_REVIEW"
    assert sop["reviewed_by"] is None
    assert sop["published_at"] is None
    assert f"sop:venue-alpha:{sop_id}" not in vector_store.documents

    knowledge = await database.fetch_one(
        "SELECT * FROM knowledge_documents WHERE id = ?",
        (f"sop-{sop_id}",),
    )
    assert knowledge is None
    versions = await database.fetch_all(
        "SELECT status FROM sop_versions WHERE sop_id = ? ORDER BY created_at",
        (sop_id,),
    )
    assert [version["status"] for version in versions] == ["DRAFT", "IN_REVIEW"]
    failed_audit = await database.fetch_one(
        "SELECT * FROM audit_logs WHERE resource_type = 'sop' AND resource_id = ? AND action = 'SOP_PUBLISH_FAILED'",
        (str(sop_id),),
    )
    assert failed_audit is not None
    await database.close()


@pytest.mark.asyncio
async def test_persona_interview_survives_restart_and_enforces_tenant_binding(tmp_path, monkeypatch):
    async def deterministic_parse(self, question_id, answer, job_title, trace_id, venue_id):
        return [
            {
                "trigger": f"问题{question_id}:{answer}",
                "behavior": f"由{job_title}执行标准处置",
                "reason": f"场地{venue_id}的已验证经验",
            }
        ]

    monkeypatch.setattr(PersonaExtractSkill, "_parse_answer", deterministic_parse)
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/personas",
            headers=admin_headers,
            json={"job_title": "索道值班长", "description": "负责索道运行与极端天气停运决策"},
        )
        assert created.status_code == 200, created.text
        persona_id = created.json()["persona_id"]
        assert created.json()["trace_id"]

        started = await client.post(
            f"/admin/personas/{persona_id}/interview/start",
            headers=admin_headers,
        )
        assert started.status_code == 200, started.text
        interview_id = started.json()["interview_id"]
        assert started.json()["trace_id"]
        assert started.json()["total_questions"] == 4

        active = await client.get(
            f"/admin/personas/{persona_id}/interview/active",
            headers=admin_headers,
        )
        assert active.status_code == 200, active.text
        assert active.json()["interview"]["interview_id"] == interview_id
        assert active.json()["interview"]["current_question"] == 1
        assert active.json()["interview"]["total_questions"] == 4
        duplicate_start = await client.post(
            f"/admin/personas/{persona_id}/interview/start",
            headers=admin_headers,
        )
        assert duplicate_start.status_code == 409
        assert duplicate_start.json()["detail"]["code"] == "INTERVIEW_ALREADY_ACTIVE"

        PersonaExtractSkill._interview_state = {}
        continued = await client.post(
            f"/admin/personas/{persona_id}/interview/continue",
            headers=admin_headers,
            json={"interview_id": interview_id, "answer": "雷暴预警达到橙色时先停止新游客进站。"},
        )
        assert continued.status_code == 200, continued.text
        assert continued.json()["current_question"] == 2
        assert continued.json()["total_questions"] == 4
        assert continued.json()["trace_id"]

        resumed = await client.get(
            f"/admin/personas/{persona_id}/interview/active",
            headers=admin_headers,
        )
        assert resumed.json()["interview"]["current_question"] == 2
        assert resumed.json()["interview"]["answered_questions"] == 1

        await client.post(
            "/admin/venues",
            headers=admin_headers,
            json={"id": "venue-beta", "name": "南麓游客中心"},
        )
        await create_user(client, admin_headers, username="manager-beta", role="manager", venue_id="venue-beta")
        beta_headers = await login(client, "manager-beta", "Strong-Password-2026")
        beta_persona = await client.post(
            "/admin/personas",
            headers=beta_headers,
            json={"job_title": "游客中心主管"},
        )
        cross_tenant = await client.post(
            f"/admin/personas/{beta_persona.json()['persona_id']}/interview/continue",
            headers=beta_headers,
            json={"interview_id": interview_id, "answer": "尝试读取其他场地访谈"},
        )
        assert cross_tenant.status_code == 404
        assert cross_tenant.json()["detail"]["code"] == "INTERVIEW_NOT_FOUND"

        for question_number in range(2, 5):
            continued = await client.post(
                f"/admin/personas/{persona_id}/interview/continue",
                headers=admin_headers,
                json={
                    "interview_id": interview_id,
                    "answer": f"第{question_number}轮真实访谈回答",
                },
            )
            assert continued.status_code == 200, continued.text

        assert continued.json()["stage"] == "summary"
        assert continued.json()["current_question"] == 4
        assert continued.json()["total_questions"] == 4
        summary = await client.get(
            f"/admin/personas/{persona_id}/interview/active",
            headers=admin_headers,
        )
        assert summary.json()["interview"]["stage"] == "summary"
        assert summary.json()["interview"]["prompt_finalize"] is True
        PersonaExtractSkill._interview_state = {}
        finalized = await client.post(
            f"/admin/personas/{persona_id}/interview/finalize",
            headers=admin_headers,
            json={"interview_id": interview_id},
        )
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["persona_id"] == persona_id
        assert finalized.json()["total_entries"] == 4
        assert finalized.json()["trace_id"]

        no_active = await client.get(
            f"/admin/personas/{persona_id}/interview/active",
            headers=admin_headers,
        )
        assert no_active.status_code == 200
        assert no_active.json()["interview"] is None

        deleted = await client.delete(f"/admin/personas/{persona_id}", headers=admin_headers)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["trace_id"]

    interview = await database.fetch_one(
        "SELECT * FROM persona_interviews WHERE id = ? AND venue_id = ?",
        (interview_id, "venue-alpha"),
    )
    assert interview["status"] == "COMPLETED"
    assert interview["current_question"] == 6
    actions = await database.fetch_all(
        "SELECT action FROM audit_logs WHERE resource_type IN ('persona', 'persona_interview') ORDER BY created_at",
    )
    assert {
        "PERSONA_CREATED",
        "PERSONA_INTERVIEW_STARTED",
        "PERSONA_INTERVIEW_CONTINUED",
        "PERSONA_INTERVIEW_FINALIZED",
        "PERSONA_DELETED",
    } <= {row["action"] for row in actions}
    await database.close()


@pytest.mark.asyncio
async def test_persona_chat_queries_exact_requested_persona(tmp_path, monkeypatch):
    captured = {}

    async def exact_persona_query(**kwargs):
        captured.update(kwargs)
        return {
            "reply_text": "我会先确认意识和呼吸。",
            "persona_id": kwargs["persona_id"],
            "job_title": kwargs["job_title"],
            "entries_used": 1,
            "source_note": f"基于{kwargs['job_title']}岗位处置记录推断",
        }

    monkeypatch.setattr(
        "src.memory_palace.skills.persona_extract.invoke.ask_persona",
        exact_persona_query,
    )
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        first = await client.post(
            "/admin/personas",
            headers=admin_headers,
            json={"job_title": "应急值班专家", "description": "第一份档案"},
        )
        second = await client.post(
            "/admin/personas",
            headers=admin_headers,
            json={"job_title": "应急值班专家", "description": "第二份档案"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        persona_id = second.json()["persona_id"]

        response = await client.post(
            f"/admin/personas/{persona_id}/chat",
            headers=admin_headers,
            json={"question": "游客意识不清时先做什么？"},
        )

    assert response.status_code == 200, response.text
    assert captured["persona_id"] == persona_id
    await database.close()


@pytest.mark.asyncio
async def test_persona_chat_records_failed_audit_when_llm_is_unavailable(tmp_path, monkeypatch):
    async def fail_persona_query(**kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "src.memory_palace.skills.persona_extract.invoke.ask_persona",
        fail_persona_query,
    )
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/personas",
            headers=admin_headers,
            json={"job_title": "安保班长", "description": "现场安全处置"},
        )
        persona_id = created.json()["persona_id"]

        response = await client.post(
            f"/admin/personas/{persona_id}/chat",
            headers=admin_headers,
            json={"question": "游客倒地时先做什么？"},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LLM_UNAVAILABLE"
    failed_audit = await database.fetch_one(
        """
        SELECT * FROM audit_logs
        WHERE action = 'PERSONA_QUERY_FAILED' AND resource_id = ? AND outcome = 'FAILED'
        """,
        (persona_id,),
    )
    assert failed_audit is not None
    assert json.loads(failed_audit["metadata_json"])["error_type"] == "RuntimeError"
    await database.close()


@pytest.mark.asyncio
async def test_manual_event_creation_records_tenant_audit(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "from_user": "operator-a",
                "raw_text": "东门闸机断电，现场已完成人流疏导",
                "event_type": "设施故障",
                "severity": "P1",
                "source_id": "showcase:event:manual-source-test",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["trace_id"]
    event = await database.fetch_one(
        "SELECT * FROM confirmed_events WHERE event_id = ?",
        (response.json()["event_id"],),
    )
    assert event["source_type"] == "HISTORY"
    assert event["push_id"] == "showcase:event:manual-source-test"
    audit = await database.fetch_one(
        "SELECT * FROM audit_logs WHERE action = 'EVENT_CREATED' AND resource_id = ?",
        (response.json()["event_id"],),
    )
    assert audit["venue_id"] == "venue-alpha"
    assert audit["outcome"] == "SUCCEEDED"
    await database.close()


@pytest.mark.asyncio
async def test_manual_event_creation_rolls_back_when_vector_write_fails(tmp_path, monkeypatch):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)

    def fail_vector_write(*args, **kwargs):
        raise RuntimeError("vector unavailable")

    monkeypatch.setattr(vector_store, "upsert_experience", fail_vector_write)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "from_user": "operator-a",
                "raw_text": "东门闸机断电",
                "event_type": "设施故障",
                "severity": "P1",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EVENT_CREATE_FAILED"
    assert await database.fetch_one("SELECT event_id FROM confirmed_events") is None
    failed_audit = await database.fetch_one(
        "SELECT * FROM audit_logs WHERE action = 'EVENT_CREATE_FAILED' AND outcome = 'FAILED'",
    )
    assert failed_audit is not None
    await database.close()


@pytest.mark.asyncio
async def test_manual_event_creation_rolls_back_when_success_audit_fails(tmp_path, monkeypatch):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    original_execute = database.execute

    async def fail_success_audit(sql, parameters=()):
        if "INSERT INTO audit_logs" in sql and len(parameters) > 2 and parameters[2] == "EVENT_CREATED":
            raise RuntimeError("audit unavailable")
        return await original_execute(sql, parameters)

    monkeypatch.setattr(database, "execute", fail_success_audit)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "from_user": "operator-a",
                "raw_text": "东门闸机断电",
                "event_type": "设施故障",
                "severity": "P1",
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EVENT_CREATE_FAILED"
    assert await database.fetch_one("SELECT event_id FROM confirmed_events") is None
    assert vector_store.documents == {}
    failed_audit = await database.fetch_one(
        "SELECT * FROM audit_logs WHERE action = 'EVENT_CREATE_FAILED' AND outcome = 'FAILED'",
    )
    assert failed_audit is not None
    await database.close()


@pytest.mark.asyncio
async def test_cross_tenant_session_close_is_denied_and_audited(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    now = time.time()
    await database.execute(
        """
        INSERT INTO sessions (
            session_id, user_id, venue_id, agent_name, message_count,
            stage, created_at, updated_at
        ) VALUES (?, ?, ?, '', 0, 'ACTIVE', ?, ?)
        """,
        ("session-foreign", "user-foreign", "venue-beta", now, now),
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.delete("/sessions/session-foreign", headers=admin_headers)
        await database.execute(
            """
            INSERT INTO audit_logs (
                venue_id, user_id, action, resource_type, resource_id,
                outcome, trace_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "venue-alpha",
                "legacy-user",
                "CONTROLLED_ACTION_REQUESTED",
                "approval",
                "legacy-approval",
                "PENDING",
                "trace-legacy-controlled-action",
                json.dumps({"approval_status": "PENDING"}),
                now,
            ),
        )
        registry = await client.get("/admin/feature-registry", headers=admin_headers)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"
    session = await database.fetch_one(
        "SELECT stage FROM sessions WHERE session_id = ?",
        ("session-foreign",),
    )
    assert session["stage"] == "ACTIVE"
    audit = await database.fetch_one(
        "SELECT * FROM audit_logs WHERE action = 'SESSION_CLOSE_DENIED' AND resource_id = ?",
        ("session-foreign",),
    )
    assert audit["venue_id"] == "venue-alpha"
    assert audit["outcome"] == "DENIED"
    assert registry.status_code == 200, registry.text
    items = {item["id"]: item for item in registry.json()["items"]}
    authz = items["MVP-PLATFORM-AUTHZ"]
    assert "跨租户访问拒绝审计" in authz["acceptance"]["satisfied"]
    denied_evidence = [
        row
        for row in authz["runtime_evidence"]
        if row.get("action") == "SESSION_CLOSE_DENIED"
    ]
    assert denied_evidence[0]["outcome"] == "DENIED"
    approvals = items["MVP-BIZ-009"]
    assert "受控动作申请审计" in approvals["acceptance"]["satisfied"]
    legacy_evidence = [
        row
        for row in approvals["runtime_evidence"]
        if row.get("resource_id") == "legacy-approval"
    ]
    assert legacy_evidence[0]["outcome"] == "PENDING"
    await database.close()


@pytest.mark.asyncio
async def test_admin_runtime_endpoints_enforce_expected_roles(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous_metrics = await client.get("/admin/metrics")
        anonymous_permissions = await client.get("/admin/permissions/tools")

        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        await create_user(client, admin_headers, username="runtime-manager", role="manager")
        await create_user(client, admin_headers, username="runtime-operator", role="operator")
        manager_headers = await login(client, "runtime-manager", "Strong-Password-2026")
        operator_headers = await login(client, "runtime-operator", "Strong-Password-2026")

        operator_metrics = await client.get("/admin/metrics", headers=operator_headers)
        manager_permissions = await client.get("/admin/permissions/tools", headers=manager_headers)
        operator_permissions = await client.get("/admin/permissions/tools", headers=operator_headers)

    assert anonymous_metrics.status_code == 401
    assert anonymous_permissions.status_code == 401
    assert operator_metrics.status_code == 200
    assert manager_permissions.status_code == 200
    assert operator_permissions.status_code == 403
    assert operator_permissions.json()["detail"]["code"] == "AUTH_FORBIDDEN"
    await database.close()


@pytest.mark.asyncio
async def test_admin_runtime_reloads_are_audited(tmp_path, monkeypatch):
    class HotReloadManager:
        def __init__(self):
            self.reloaded = []

        async def reload_skill(self, skill_name):
            self.reloaded.append(skill_name)

    manager = HotReloadManager()
    reload_events = []
    monkeypatch.setattr(
        "src.memory_palace.config.config_manager.config.reload",
        lambda: reload_events.append("config_manager"),
    )
    monkeypatch.setattr(
        "src.memory_palace.config.app_settings.reload_settings",
        lambda: reload_events.append("app_settings"),
    )
    monkeypatch.setattr("src.memory_palace.skills.reload_skill", lambda skill_name: None)
    monkeypatch.setattr(
        "src.memory_palace.core.hot_reload.get_hot_reload_manager",
        lambda: manager,
    )
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        config_response = await client.post("/admin/config/reload", headers=admin_headers)
        skill_response = await client.post("/skills/router/reload", headers=admin_headers)

    assert config_response.status_code == 200, config_response.text
    assert config_response.json()["trace_id"]
    assert skill_response.status_code == 200, skill_response.text
    assert skill_response.json()["trace_id"]
    assert reload_events == ["config_manager", "app_settings"]
    assert manager.reloaded == ["router"]
    actions = await database.fetch_all(
        "SELECT action, resource_id, outcome FROM audit_logs WHERE action IN ('CONFIG_RELOADED', 'SKILL_RELOADED')",
    )
    assert {(row["action"], row["resource_id"], row["outcome"]) for row in actions} == {
        ("CONFIG_RELOADED", "runtime", "SUCCEEDED"),
        ("SKILL_RELOADED", "router", "SUCCEEDED"),
    }
    await database.close()


@pytest.mark.asyncio
async def test_watcher_policy_run_and_finding_close_persist_evidence(tmp_path, monkeypatch):
    app, database, _, scheduler = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        invalid = await client.post(
            "/admin/watcher/policies",
            headers=admin_headers,
            json={"name": "无效计划", "schedule_cron": "bad cron value"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "WATCHER_CRON_INVALID"

        created = await client.post(
            "/admin/watcher/policies",
            headers=admin_headers,
            json={
                "name": "每日未闭环巡检",
                "description": "检查 SLA、任务和 SOP 完整性",
                "schedule_cron": "0 10 * * *",
                "enabled": True,
                "check_types": ["SLA", "TASK", "SOP"],
            },
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["policy"]["id"]
        assert scheduler.reload_count == 1

        run = await client.post(f"/admin/watcher/policies/{policy_id}/run", headers=admin_headers)
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "SUCCEEDED"
        assert run.json()["target_count"] == 0
        assert run.json()["model"] is None

        now = time.time()
        finding_id = "finding-test-1"
        await database.execute(
            """
            INSERT INTO watcher_findings (
                id, run_id, policy_id, venue_id, finding_type, severity,
                title, description, source_type, source_id, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
            """,
            (
                finding_id,
                run.json()["run_id"],
                policy_id,
                "venue-alpha",
                "SLA",
                "P1",
                "P1 事件接近 SLA",
                "事件仍未完成现场反馈。",
                "event",
                "event-test-1",
                now,
                now,
            ),
        )
        closed = await client.post(
            f"/admin/watcher/findings/{finding_id}/close",
            headers=admin_headers,
            json={"resolution": "已联系当班经理并补充现场反馈。"},
        )
        assert closed.status_code == 200
        row = await database.fetch_one("SELECT * FROM watcher_findings WHERE id = ?", (finding_id,))
        assert row["status"] == "CLOSED"
        assert row["closed_at"] is not None

        runs = await client.get("/admin/watcher/runs", headers=admin_headers)
        assert runs.json()["runs"][0]["trace_id"] == run.json()["trace_id"]

    await database.close()


@pytest.mark.asyncio
async def test_watcher_run_preserves_model_violation_reason_and_severity_level(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "from_user": "watcher-regression-operator",
                "raw_text": "东门闸机断电超过十分钟，现场尚未反馈隔离结果。",
                "event_type": "设施故障",
                "severity": "P1",
            },
        )
        assert event.status_code == 200, event.text
        event_id = event.json()["event_id"]
        violation_reason = "P1 事件已超过 10 分钟 SLA，且现场未反馈闸机断电隔离结果。"

        async def return_model_audit(**kwargs):
            assert kwargs["model"] == "deepseek-v4-flash"
            return LLMResponse(
                content=json.dumps(
                    {
                        "is_violation_found": True,
                        "escalated_cases": [
                            {
                                "case_id": event_id,
                                "violation_reason": violation_reason,
                                "severity_level": "P1",
                            }
                        ],
                        "audit_score": 80,
                        "summary_message": "本次巡检发现 1 起 P1 SLA 超时违规。",
                    },
                    ensure_ascii=False,
                ),
                tokens_used=128,
                model_name="deepseek-v4-flash",
                latency_seconds=0.01,
                is_mock=False,
            )

        monkeypatch.setattr(
            "src.memory_palace.skills.watcher.skill.llm_client.ask",
            return_model_audit,
        )
        created = await client.post(
            "/admin/watcher/policies",
            headers=admin_headers,
            json={
                "name": "模型字段映射回归巡检",
                "schedule_cron": "0 10 * * *",
                "enabled": True,
                "check_types": ["SLA"],
            },
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["policy"]["id"]

        run = await client.post(f"/admin/watcher/policies/{policy_id}/run", headers=admin_headers)
        assert run.status_code == 200, run.text
        finding = run.json()["findings"][0]
        assert (finding["severity"], finding["description"]) == ("P1", violation_reason)

        findings = await client.get("/admin/watcher/findings", headers=admin_headers)
        persisted = next(item for item in findings.json()["findings"] if item["id"] == finding["id"])
        assert (persisted["severity"], persisted["description"]) == ("P1", violation_reason)

    await database.close()


@pytest.mark.asyncio
async def test_watcher_policy_reuses_matching_open_finding_across_runs(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        event = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "from_user": "watcher-idempotency-operator",
                "raw_text": "东门闸机断电超过十分钟，现场仍未反馈隔离结果。",
                "event_type": "设施故障",
                "severity": "P1",
            },
        )
        assert event.status_code == 200, event.text
        event_id = event.json()["event_id"]
        violation_reason = "P1 事件已超过 10 分钟 SLA，现场仍未反馈隔离结果。"

        async def return_same_model_audit(**kwargs):
            assert kwargs["model"] == "deepseek-v4-flash"
            return LLMResponse(
                content=json.dumps(
                    {
                        "is_violation_found": True,
                        "escalated_cases": [
                            {
                                "case_id": event_id,
                                "source_type": "event",
                                "source_id": event_id,
                                "issue_type": "SLA_EXCEEDED",
                                "title": "事件处置已超过 SLA",
                                "violation_reason": violation_reason,
                                "severity_level": "P1",
                            }
                        ],
                        "audit_score": 80,
                        "summary_message": "本次巡检发现 1 起 P1 SLA 超时违规。",
                    },
                    ensure_ascii=False,
                ),
                tokens_used=128,
                model_name="deepseek-v4-flash",
                latency_seconds=0.01,
                is_mock=False,
            )

        monkeypatch.setattr(
            "src.memory_palace.skills.watcher.skill.llm_client.ask",
            return_same_model_audit,
        )
        created = await client.post(
            "/admin/watcher/policies",
            headers=admin_headers,
            json={
                "name": "重复异常幂等巡检",
                "schedule_cron": "0 10 * * *",
                "enabled": True,
                "check_types": ["SLA"],
            },
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["policy"]["id"]

        first = await client.post(
            f"/admin/watcher/policies/{policy_id}/run",
            headers=admin_headers,
        )
        await asyncio.sleep(0.02)
        second = await client.post(
            f"/admin/watcher/policies/{policy_id}/run",
            headers=admin_headers,
        )
        visible = await client.get(
            "/admin/watcher/findings?status=OPEN",
            headers=admin_headers,
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_body = first.json()
    second_body = second.json()
    first_finding = first_body["findings"][0]
    second_finding = second_body["findings"][0]
    assert first_body["run_id"] != second_body["run_id"]
    assert first_body["finding_count"] == second_body["finding_count"] == 1
    assert first_finding["id"] == second_finding["id"]
    assert first_finding.get("reused") is False
    assert second_finding.get("reused") is True
    assert first_finding["issue_fingerprint"] == second_finding["issue_fingerprint"]
    assert second_finding["updated_at"] > first_finding["updated_at"]
    matching_open = [
        finding
        for finding in visible.json()["findings"]
        if finding["policy_id"] == policy_id
        and finding["source_type"] == "event"
        and finding["source_id"] == event_id
        and finding["finding_type"] == "SLA_EXCEEDED"
    ]
    assert len(matching_open) == 1
    assert matching_open[0]["id"] == first_finding["id"]
    await database.close()


@pytest.mark.asyncio
async def test_watcher_restart_recovery_finalizes_interrupted_run(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/watcher/policies",
            headers=admin_headers,
            json={"name": "重启恢复巡检", "schedule_cron": "*/10 * * * *", "enabled": True},
        )
        policy_id = created.json()["policy"]["id"]

    await database.execute(
        """
        INSERT INTO watcher_runs (
            id, policy_id, venue_id, trigger_source, status, trace_id,
            target_count, finding_count, result_json, started_at
        ) VALUES (?, ?, ?, ?, 'RUNNING', ?, 0, 0, '{}', ?)
        """,
        ("interrupted-run", policy_id, "venue-alpha", "SCHEDULED", "interrupted-trace", time.time()),
    )
    await database.execute(
        """
        INSERT INTO watcher_findings (
            id, run_id, policy_id, venue_id, finding_type, severity,
            title, description, source_type, source_id, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
        """,
        (
            "interrupted-finding",
            "interrupted-run",
            policy_id,
            "venue-alpha",
            "SLA_EXCEEDED",
            "P1",
            "重启前尚未完成的巡检发现",
            "该发现属于未完成的巡检运行。",
            "event",
            "event-interrupted",
            time.time(),
            time.time(),
        ),
    )

    assert await recover_interrupted_watcher_runs(database) == 1
    recovered = await database.fetch_one(
        "SELECT status, error, completed_at FROM watcher_runs WHERE id = ?",
        ("interrupted-run",),
    )
    assert recovered["status"] == "FAILED"
    assert recovered["error"] == "Watcher run interrupted by application restart"
    assert recovered["completed_at"] is not None
    assert await database.fetch_all(
        "SELECT id FROM watcher_findings WHERE run_id = ? AND status = 'OPEN'",
        ("interrupted-run",),
    ) == []
    await database.close()


@pytest.mark.asyncio
async def test_watcher_cancellation_finalizes_running_record(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        created = await client.post(
            "/admin/watcher/policies",
            headers=admin_headers,
            json={"name": "取消收口巡检", "schedule_cron": "*/10 * * * *", "enabled": True},
        )
        policy_id = created.json()["policy"]["id"]

    async def cancelled_run(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "src.memory_palace.core.watcher_runtime.WatcherSkill.run",
        cancelled_run,
    )
    with pytest.raises(asyncio.CancelledError):
        await run_watcher_policy(
            database,
            policy_id=policy_id,
            venue_id="venue-alpha",
            trigger_source="SCHEDULED",
        )

    cancelled = await database.fetch_one(
        "SELECT status, error, completed_at FROM watcher_runs WHERE policy_id = ?",
        (policy_id,),
    )
    assert cancelled["status"] == "FAILED"
    assert cancelled["error"] == "Watcher run cancelled during application shutdown"
    assert cancelled["completed_at"] is not None
    await database.close()


@pytest.mark.asyncio
async def test_trace_timeline_aggregates_only_current_tenant_evidence(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    now = time.time()
    await database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, target_agent, reply_text, result_json, created_at, updated_at, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "message-trace-alpha",
            "trace-alpha",
            "session-trace-alpha",
            "operator-alpha",
            "venue-alpha",
            "东门闸机断电，现场已隔离故障回路。",
            "COMPLETED",
            "commander",
            "已生成处置建议。",
            json.dumps({"triggered": True, "intent": "emergency"}),
            now,
            now + 1,
            now + 1,
        ),
    )
    await database.execute(
        """
        INSERT INTO llm_call_logs (
            id, venue_id, trace_id, provider, model_name, status,
            attempt_count, latency_seconds, request_id, is_mock, created_at
        ) VALUES (?, ?, ?, 'deepseek', 'deepseek-v4-flash', 'SUCCEEDED', 1, ?, ?, 0, ?)
        """,
        ("llm-trace-alpha", "venue-alpha", "trace-alpha", 0.42, "request-trace-alpha", now + 0.4),
    )
    await database.execute(
        """
        INSERT INTO audit_logs (
            venue_id, user_id, action, resource_type, resource_id,
            outcome, trace_id, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "venue-alpha",
            "operator-alpha",
            "MESSAGE_PROCESSED",
            "message",
            "message-trace-alpha",
            "SUCCEEDED",
            "trace-alpha",
            json.dumps({"agent": "commander"}),
            now + 1,
        ),
    )
    await database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, from_user, raw_text, event_type, severity,
            memory_content, venue_id, source_type, status, trace_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'LIVE', 'OPEN', ?, ?, ?)
        """,
        (
            "event-trace-alpha",
            "operator-alpha",
            "东门闸机断电，现场已隔离故障回路。",
            "设施故障",
            "P1",
            "闸机断电处置记录",
            "venue-alpha",
            "trace-alpha",
            now + 1,
            now + 1,
        ),
    )
    await database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
        """,
        (
            "message-trace-foreign",
            "trace-foreign",
            "session-trace-foreign",
            "operator-foreign",
            "venue-beta",
            "其他场地事件",
            now,
            now,
        ),
    )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.get("/admin/traces/trace-alpha", headers=admin_headers)
        foreign = await client.get("/admin/traces/trace-foreign", headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["trace_id"] == "trace-alpha"
    assert payload["status"] == "SUCCEEDED"
    assert payload["summary"]["model_calls"] == 1
    assert payload["summary"]["events"] == 1
    assert payload["summary"]["audits"] == 1
    assert payload["message_run"]["message_id"] == "message-trace-alpha"
    assert {item["kind"] for item in payload["timeline"]} >= {"MESSAGE", "MODEL", "AUDIT", "EVENT"}
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "TRACE_NOT_FOUND"
    await database.close()


@pytest.mark.asyncio
async def test_trace_timeline_includes_only_tasks_linked_by_current_trace_audit(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    now = time.time()
    session_id = "session-shared-task-traces"
    await database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
        """,
        (
            "message-task-trace-alpha",
            "trace-task-alpha",
            session_id,
            "operator-alpha",
            "venue-alpha",
            "生成第一批处置任务",
            now,
            now,
        ),
    )
    for task_id, description in (
        ("task-trace-alpha", "疏散东门排队游客"),
        ("task-trace-beta", "复核西门备用通道"),
    ):
        await database.execute(
            """
            INSERT INTO tasks (
                id, venue_id, session_id, description, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (task_id, "venue-alpha", session_id, description, now, now),
        )
    for trace_id, task_id in (
        ("trace-task-alpha", "task-trace-alpha"),
        ("trace-task-beta", "task-trace-beta"),
    ):
        await database.execute(
            """
            INSERT INTO audit_logs (
                venue_id, user_id, action, resource_type, resource_id,
                outcome, trace_id, metadata_json, created_at
            ) VALUES (?, ?, 'TASK_CREATED', 'task', ?, 'SUCCEEDED', ?, '{}', ?)
            """,
            ("venue-alpha", "operator-alpha", task_id, trace_id, now),
        )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.get("/admin/traces/trace-task-alpha", headers=admin_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["tasks"] == 1
    assert {
        item["resource_id"] for item in payload["timeline"] if item["kind"] == "TASK"
    } == {"task-trace-alpha"}
    await database.close()


@pytest.mark.asyncio
async def test_admin_operational_outputs_do_not_expose_sensitive_runtime_values(
    tmp_path,
    monkeypatch,
):
    sensitive_values = {
        "api_key": "DUMMY_API_KEY_VALUE_SHOULD_NOT_LEAK",
        "authorization": "Bearer DUMMY_AUTH_TOKEN_SHOULD_NOT_LEAK",
        "cookie": "session=DUMMY_COOKIE_VALUE_SHOULD_NOT_LEAK",
        "password": "DUMMY_PASSWORD_VALUE_SHOULD_NOT_LEAK",
        "prompt": "DUMMY_FULL_PROMPT_SHOULD_NOT_LEAK",
        "storage_path": "/app/data/attachments/private/dummy-sensitive.png",
        "exception": "DUMMY_RAW_EXCEPTION_SHOULD_NOT_LEAK",
    }
    raw_error = (
        "401 Unauthorized; Authorization: "
        f"{sensitive_values['authorization']}; api_key={sensitive_values['api_key']}; "
        f"Cookie: {sensitive_values['cookie']}; password={sensitive_values['password']}; "
        f"prompt={sensitive_values['prompt']}; storage_path={sensitive_values['storage_path']}; "
        f"{sensitive_values['exception']}"
    )

    class QueueStub:
        async def list_dead_letters(self, limit=20):
            return [
                {
                    "id": "1700000000700-0",
                    "created_at_ms": 1700000000700,
                    "message": {
                        "msg_id": "message-sensitive-output",
                        "trace_id": "trace-sensitive-output",
                        "session_id": "session-sensitive-output",
                        "venue_id": "venue-alpha",
                        "content": sensitive_values["prompt"],
                        **sensitive_values,
                    },
                    "error": raw_error,
                    "retries": 3,
                }
            ][:limit]

    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    app.state.message_queue = QueueStub()
    now = time.time()
    await database.execute(
        """
        INSERT INTO message_runs (
            message_id, trace_id, session_id, user_id, venue_id, content,
            status, channel, reply_text, result_json, error,
            created_at, updated_at, processed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'FAILED', 'WECOM_SIMULATOR', ?, ?, ?, ?, ?, ?)
        """,
        (
            "message-sensitive-output",
            "trace-sensitive-output",
            "session-sensitive-output",
            "mvp-admin",
            "venue-alpha",
            "现场任务处理失败，请管理员排查。",
            "任务处理失败。",
            json.dumps(sensitive_values, ensure_ascii=False),
            raw_error,
            now,
            now,
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO llm_call_logs (
            id, venue_id, trace_id, agent_id, agent_name, provider, model_name,
            status, attempt_count, latency_seconds, prompt_tokens,
            completion_tokens, total_tokens, request_id, error_type,
            error_message, is_mock, created_at
        ) VALUES (?, ?, ?, ?, ?, 'deepseek', 'deepseek-v4-flash', 'FAILED',
            2, ?, 12, 0, 12, ?, 'AuthenticationError', ?, 0, ?)
        """,
        (
            "llm-sensitive-output",
            "venue-alpha",
            "trace-sensitive-output",
            "Commander",
            "commander",
            0.37,
            "request-sensitive-output",
            raw_error,
            now + 0.1,
        ),
    )
    await database.execute(
        """
        INSERT INTO audit_logs (
            venue_id, user_id, action, resource_type, resource_id,
            outcome, trace_id, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, 'FAILED', ?, ?, ?)
        """,
        (
            "venue-alpha",
            "mvp-admin",
            "SENSITIVE_OPERATION_FAILED",
            "message_run",
            "message-sensitive-output",
            "trace-sensitive-output",
            json.dumps({**sensitive_values, "raw_error": raw_error}, ensure_ascii=False),
            now + 0.2,
        ),
    )
    await database.execute(
        """
        INSERT INTO confirmed_events (
            event_id, business_id, push_id, from_user, raw_text, event_type,
            severity, memory_content, venue_id, source_type, status, trace_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'P1', ?, ?, 'LIVE', 'OPEN', ?, ?, ?)
        """,
        (
            "event-sensitive-output",
            "SJ-SENSITIVE-001",
            "message-sensitive-output",
            "mvp-admin",
            "现场任务处理失败，请管理员排查。",
            "运行故障",
            "现场运行故障记录",
            "venue-alpha",
            "trace-sensitive-output",
            now + 0.3,
            now + 0.3,
        ),
    )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        responses = {
            "llm": await client.get(
                "/admin/llm-calls",
                params={"trace_id": "trace-sensitive-output"},
                headers=admin_headers,
            ),
            "audit": await client.get(
                "/admin/audit-logs",
                params={"trace_id": "trace-sensitive-output"},
                headers=admin_headers,
            ),
            "trace": await client.get(
                "/admin/traces/trace-sensitive-output",
                headers=admin_headers,
            ),
            "event": await client.get(
                "/admin/events/event-sensitive-output",
                headers=admin_headers,
            ),
            "dead_letters": await client.get(
                "/admin/dead-letters",
                headers=admin_headers,
            ),
        }

    assert all(response.status_code == 200 for response in responses.values()), {
        name: response.text for name, response in responses.items()
    }
    payloads = {name: response.json() for name, response in responses.items()}
    serialized = json.dumps(payloads, ensure_ascii=False)
    for sensitive_value in sensitive_values.values():
        assert sensitive_value not in serialized
    assert "DUMMY_RAW_EXCEPTION_SHOULD_NOT_LEAK" not in serialized

    llm_call = payloads["llm"]["llm_calls"][0]
    assert set(llm_call) == {
        "id",
        "venue_id",
        "trace_id",
        "agent_id",
        "agent_name",
        "provider",
        "model_name",
        "status",
        "attempt_count",
        "latency_seconds",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "request_id",
        "error_type",
        "error_summary",
        "is_mock",
        "created_at",
    }
    assert llm_call["trace_id"] == "trace-sensitive-output"
    assert llm_call["status"] == "FAILED"
    assert llm_call["model_name"] == "deepseek-v4-flash"
    assert llm_call["latency_seconds"] == 0.37
    assert llm_call["error_summary"] == "模型服务鉴权失败，请检查模型凭据后重试。"

    audit_metadata = payloads["audit"]["audit_logs"][0]["metadata"]
    assert not ({"api_key", "authorization", "cookie", "password", "prompt", "storage_path"} & set(audit_metadata))
    assert audit_metadata["raw_error"] == "操作鉴权失败，请检查依赖服务凭据后重试。"

    trace_result = payloads["trace"]["message_run"]["result"]
    assert not ({"api_key", "authorization", "cookie", "password", "prompt", "storage_path"} & set(trace_result))
    assert payloads["trace"]["message_run"]["error_summary"] == "操作鉴权失败，请检查依赖服务凭据后重试。"

    model_failure = next(
        entry
        for entry in payloads["event"]["dossier"]["journey_timeline"]
        if entry["technical"]["activity_type"] == "MODEL_CALL_FAILED"
    )
    assert model_failure["summary"] == "模型服务鉴权失败，请检查模型凭据后重试。"

    dead_letter = payloads["dead_letters"]["dead_letters"][0]
    assert dead_letter["message"] == {
        "msg_id": "message-sensitive-output",
        "trace_id": "trace-sensitive-output",
        "session_id": "session-sensitive-output",
        "venue_id": "venue-alpha",
    }
    assert dead_letter["error"] == "任务处理鉴权失败，请检查依赖服务凭据后重试。"
    await database.close()
