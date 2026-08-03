from __future__ import annotations

import time

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.auth import create_token
from src.memory_palace.api.v1.endpoints.management import router as management_router
from src.memory_palace.skills import _auto_register_skills


EXPECTED_AGENTS = {
    "ContextTrigger",
    "Router",
    "Commander",
    "MemoryOps",
    "Persona",
    "PersonaExtract",
    "TodoWrite",
    "Watcher",
}


class DiagnosticsDatabaseStub:
    backend_name = "postgresql"

    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "FROM users WHERE id" in sql:
            user_id = parameters[0]
            role = "manager" if user_id == "manager-user" else "admin"
            return {
                "id": user_id,
                "username": role,
                "role": role,
                "venue_id": "venue-alpha",
                "status": "ACTIVE",
            }
        if "SELECT 1 AS ok" in sql:
            return {"ok": 1}
        return None

    async def fetch_all(self, sql: str, parameters: tuple = ()):
        if "FROM llm_call_logs" not in sql:
            return []
        assert parameters == ("venue-alpha", "deepseek-v4-flash")
        now = time.time()
        return [
            {
                "agent_id": agent_id,
                "agent_name": agent_id,
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "status": "SUCCEEDED",
                "is_mock": False,
                "request_id": f"request-{index}",
                "trace_id": f"trace-{index}",
                "created_at": now - index,
                "prompt": "private-prompt-must-not-leak",
                "response_text": "private-model-output-must-not-leak",
            }
            for index, agent_id in enumerate(sorted(EXPECTED_AGENTS), start=1)
        ]


class SQLiteDiagnosticsDatabaseStub(DiagnosticsDatabaseStub):
    backend_name = "sqlite"


class QueueStub:
    async def diagnostics(self):
        return {
            "backend": "redis_streams",
            "connected": True,
            "stream_depth": 4,
            "pending": 1,
            "lag": 2,
            "dead_letter_depth": 0,
            "redis_password": "must-not-leak",
        }


class WorkerStub:
    def diagnostics(self):
        return {
            "status": "RUNNING",
            "running": True,
            "backend": "redis_streams",
            "concurrency": 5,
            "inflight": 1,
            "started_at": 1_754_200_000.0,
            "secret": "must-not-leak",
        }


class VectorStoreStub:
    def health(self):
        return {
            "status": "healthy",
            "backend": "chromadb_http",
            "heartbeat": 123,
            "url": "http://credential@chromadb.internal",
        }


def _access_header(*, role: str) -> dict[str, str]:
    user_id = "manager-user" if role == "manager" else "admin-user"
    token, _token_id, _expires_at = create_token(
        user_id=user_id,
        username=role,
        role=role,
        venue_id="venue-alpha",
        token_type="access",
        ttl_seconds=300,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_runtime_diagnostics_reports_unified_safe_operational_status(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "diagnostic-deepseek-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setenv("WECHAT_CORP_SECRET", "real-wecom-secret-must-not-leak")
    _auto_register_skills()

    app = FastAPI(version="1.2.3")
    app.state.db_client = DiagnosticsDatabaseStub()
    app.state.message_queue = QueueStub()
    app.state.message_worker = WorkerStub()
    app.state.vector_store = VectorStoreStub()
    app.state.runtime_instance_id = "app-instance-uat"
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/diagnostics", headers=_access_header(role="admin"))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["runtime"] == {
        "app": {
            "status": "healthy",
            "version": "1.2.3",
            "instance_id": "app-instance-uat",
        },
        "postgresql": {"status": "healthy"},
        "redis": {
            "status": "healthy",
            "backend": "redis_streams",
            "stream_depth": 4,
            "pending": 1,
            "lag": 2,
            "dead_letter_depth": 0,
        },
        "chromadb": {"status": "healthy", "backend": "chromadb_http"},
        "worker": {
            "status": "healthy",
            "running": True,
            "backend": "redis_streams",
            "concurrency": 5,
            "inflight": 1,
            "started_at": 1_754_200_000.0,
        },
    }

    agents = {agent["id"]: agent for agent in payload["agents"]}
    assert set(agents) == EXPECTED_AGENTS
    assert all(agent["registered"] for agent in agents.values())
    assert all(agent["status"] == "LIVE_VERIFIED" for agent in agents.values())
    assert {agent["registry_name"] for agent in agents.values()} == {
        "context_trigger",
        "router",
        "commander",
        "memory_ops",
        "persona",
        "persona_extract",
        "todo_write",
        "watcher",
    }
    assert all(agent["evidence"]["is_mock"] is False for agent in agents.values())
    assert payload["deepseek"] == {
        "status": "READY",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "configured": True,
        "mock_enabled": False,
        "live_verified": True,
        "verified_agent_count": 8,
        "required_agent_count": 8,
    }
    assert payload["channels"]["wecom_simulator"]["status"] == "SIMULATOR_READY"
    assert payload["channels"]["real_wecom"] == {
        "status": "DISABLED_BY_POLICY",
        "policy_mode": "WECOM_SIMULATOR_ONLY",
        "client_initialized": False,
        "enqueue_enabled": False,
        "delivery_enabled": False,
    }

    response_text = response.text.lower()
    for sensitive_value in (
        "diagnostic-deepseek-secret",
        "real-wecom-secret-must-not-leak",
        "must-not-leak",
        "private-prompt-must-not-leak",
        "private-model-output-must-not-leak",
        "redis_password",
        '"secret"',
        '"token"',
        '"cookie"',
    ):
        assert sensitive_value not in response_text


@pytest.mark.asyncio
async def test_runtime_diagnostics_is_admin_only(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    app = FastAPI()
    app.state.db_client = DiagnosticsDatabaseStub()
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/diagnostics", headers=_access_header(role="manager"))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_runtime_diagnostics_degrades_when_deepseek_secret_file_is_unreadable(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY_FILE", str(tmp_path / "missing-secret"))
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    _auto_register_skills()

    app = FastAPI()
    app.state.db_client = DiagnosticsDatabaseStub()
    app.state.message_queue = QueueStub()
    app.state.message_worker = WorkerStub()
    app.state.vector_store = VectorStoreStub()
    app.state.runtime_instance_id = "app-instance-uat"
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/diagnostics", headers=_access_header(role="admin"))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["deepseek"]["status"] == "BLOCKED"
    assert payload["deepseek"]["configured"] is False


@pytest.mark.asyncio
async def test_runtime_diagnostics_does_not_report_sqlite_as_healthy_postgresql(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "diagnostic-deepseek-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    _auto_register_skills()

    app = FastAPI()
    app.state.db_client = SQLiteDiagnosticsDatabaseStub()
    app.state.message_queue = QueueStub()
    app.state.message_worker = WorkerStub()
    app.state.vector_store = VectorStoreStub()
    app.state.runtime_instance_id = "app-instance-uat"
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/diagnostics", headers=_access_header(role="admin"))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["runtime"]["postgresql"] == {"status": "unhealthy"}
