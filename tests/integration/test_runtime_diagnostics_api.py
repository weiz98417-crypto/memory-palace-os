from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.auth import create_token
from src.memory_palace.api.v1.endpoints.management import router as management_router
from src.memory_palace.operations import runtime_diagnostics
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
        if "FROM llm_call_logs" in sql:
            assert parameters == ("venue-alpha", "RuntimeDiagnostics")
            return {
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "status": "SUCCEEDED",
                "is_mock": False,
                "request_id": "latest-request",
                "trace_id": "latest-trace",
                "created_at": time.time(),
            }
        if "active_user_count" in sql:
            assert parameters == ("venue-alpha", "venue-alpha")
            return {
                "active_user_count": 8,
                "mapped_active_user_count": 8,
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


class ProbeOnlyDiagnosticsDatabaseStub(DiagnosticsDatabaseStub):
    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "FROM llm_call_logs" in sql:
            return {
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "status": "SUCCEEDED",
                "is_mock": False,
                "request_id": "probe-request",
                "trace_id": "probe-trace",
                "created_at": time.time(),
            }
        if "active_user_count" in sql:
            return {
                "active_user_count": 2,
                "mapped_active_user_count": 2,
            }
        return await super().fetch_one(sql, parameters)

    async def fetch_all(self, sql: str, parameters: tuple = ()):
        if "FROM llm_call_logs" in sql:
            return []
        return await super().fetch_all(sql, parameters)


class MissingSimulatorIdentityDatabaseStub(DiagnosticsDatabaseStub):
    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "FROM llm_call_logs" in sql:
            return {
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "status": "SUCCEEDED",
                "is_mock": False,
                "request_id": "probe-request",
                "trace_id": "probe-trace",
                "created_at": time.time(),
            }
        if "active_user_count" in sql:
            return {
                "active_user_count": 2,
                "mapped_active_user_count": 1,
            }
        return await super().fetch_one(sql, parameters)


class BrokenAgentEvidenceDatabaseStub(ProbeOnlyDiagnosticsDatabaseStub):
    async def fetch_all(self, sql: str, parameters: tuple = ()):
        if "FROM llm_call_logs" in sql:
            raise ConnectionError("postgresql://diagnostics-secret@database.internal")
        return await super().fetch_all(sql, parameters)


class FailedLatestProbeDatabaseStub(ProbeOnlyDiagnosticsDatabaseStub):
    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "FROM llm_call_logs" in sql:
            assert parameters == ("venue-alpha", "RuntimeDiagnostics")
            assert "status = 'SUCCEEDED'" not in sql
            return {
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "status": "FAILED",
                "is_mock": False,
                "request_id": None,
                "trace_id": "failed-probe-trace",
                "created_at": time.time(),
            }
        return await super().fetch_one(sql, parameters)


class DeepSeekProbeClientStub:
    def __init__(self):
        self.kwargs = None

    async def ask(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content="private-probe-output-must-not-leak",
            model_name="deepseek-v4-flash",
            is_mock=False,
            request_id="probe-request",
            latency_seconds=0.125,
        )


class MockDeepSeekProbeClientStub(DeepSeekProbeClientStub):
    async def ask(self, **kwargs):
        response = await super().ask(**kwargs)
        response.is_mock = True
        return response


class MissingRequestIdDeepSeekProbeClientStub(DeepSeekProbeClientStub):
    async def ask(self, **kwargs):
        response = await super().ask(**kwargs)
        response.request_id = None
        return response


class ProbeEndpointDatabaseStub(DiagnosticsDatabaseStub):
    def __init__(
        self,
        *,
        probe_evidence_persisted: bool = True,
        probe_request_id: str | None = "probe-request",
    ):
        self.executed: list[tuple[str, tuple]] = []
        self.probe_evidence_persisted = probe_evidence_persisted
        self.probe_request_id = probe_request_id

    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "FROM llm_call_logs" in sql:
            assert parameters[:3] == ("venue-alpha", "probe-trace", "RuntimeDiagnostics")
            assert isinstance(parameters[3], float)
            if not self.probe_evidence_persisted:
                return None
            return {
                "provider": "deepseek",
                "model_name": "deepseek-v4-flash",
                "status": "SUCCEEDED",
                "is_mock": False,
                "request_id": self.probe_request_id,
                "trace_id": "probe-trace",
                "created_at": time.time(),
            }
        return await super().fetch_one(sql, parameters)

    async def execute(self, sql: str, parameters: tuple = ()):
        self.executed.append((sql, parameters))


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
        "max_evidence_age_seconds": 900,
        "evidence_collection": {"status": "healthy"},
        "evidence": {
            "provider": "deepseek",
            "model_name": "deepseek-v4-flash",
            "status": "SUCCEEDED",
            "is_mock": False,
            "request_id": "latest-request",
            "trace_id": "latest-trace",
            "created_at": payload["deepseek"]["evidence"]["created_at"],
        },
    }
    assert payload["agent_coverage"] == {
        "status": "healthy",
        "registered_agent_count": 8,
        "verified_agent_count": 8,
        "required_agent_count": 8,
        "complete": True,
    }
    assert payload["channels"]["wecom_simulator"] == {
        "status": "SIMULATOR_READY",
        "entrypoint": "/simulator/wecom/",
        "active_user_count": 8,
        "mapped_active_user_count": 8,
        "unmapped_active_user_count": 0,
    }
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
async def test_deepseek_readiness_is_independent_from_eight_agent_call_coverage(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "diagnostic-deepseek-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    _auto_register_skills()

    app = FastAPI(version="1.2.3")
    app.state.db_client = ProbeOnlyDiagnosticsDatabaseStub()
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
    assert payload["deepseek"]["status"] == "READY"
    assert payload["deepseek"]["live_verified"] is True
    assert payload["agent_coverage"] == {
        "status": "healthy",
        "registered_agent_count": 8,
        "verified_agent_count": 0,
        "required_agent_count": 8,
        "complete": False,
    }
    assert all(agent["status"] == "REGISTERED_UNVERIFIED" for agent in payload["agents"])


@pytest.mark.asyncio
async def test_latest_failed_diagnostic_probe_blocks_deepseek_readiness(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "diagnostic-deepseek-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    _auto_register_skills()

    app = FastAPI(version="1.2.3")
    app.state.db_client = FailedLatestProbeDatabaseStub()
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
    assert payload["deepseek"]["live_verified"] is False
    assert payload["deepseek"]["evidence"]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_missing_agent_registration_degrades_without_conflating_call_coverage(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "diagnostic-deepseek-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    _auto_register_skills()
    registered = set(runtime_diagnostics.list_skill_names()) - {"watcher"}
    monkeypatch.setattr(runtime_diagnostics, "list_skill_names", lambda: sorted(registered))

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
    assert payload["status"] == "degraded"
    assert payload["agent_coverage"]["status"] == "unhealthy"
    assert payload["agent_coverage"]["registered_agent_count"] == 7
    assert payload["agent_coverage"]["verified_agent_count"] == 7
    watcher = next(agent for agent in payload["agents"] if agent["id"] == "Watcher")
    assert watcher["status"] == "UNREGISTERED"


@pytest.mark.asyncio
async def test_wecom_simulator_blocks_when_active_users_lack_active_identity_mapping(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "diagnostic-deepseek-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    _auto_register_skills()

    app = FastAPI(version="1.2.3")
    app.state.db_client = MissingSimulatorIdentityDatabaseStub()
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
    assert payload["channels"]["wecom_simulator"] == {
        "status": "BLOCKED",
        "entrypoint": "/simulator/wecom/",
        "active_user_count": 2,
        "mapped_active_user_count": 1,
        "unmapped_active_user_count": 1,
    }
    assert payload["channels"]["real_wecom"]["status"] == "DISABLED_BY_POLICY"


@pytest.mark.asyncio
async def test_agent_evidence_collection_failure_is_sanitized_and_degrades_diagnostics(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "diagnostic-deepseek-secret")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    _auto_register_skills()

    app = FastAPI(version="1.2.3")
    app.state.db_client = BrokenAgentEvidenceDatabaseStub()
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
    assert payload["agent_coverage"] == {
        "status": "unhealthy",
        "error_type": "ConnectionError",
        "registered_agent_count": 8,
        "verified_agent_count": 0,
        "required_agent_count": 8,
        "complete": False,
    }
    assert all(agent["status"] == "REGISTERED_UNVERIFIED" for agent in payload["agents"])
    assert "diagnostics-secret" not in response.text
    assert "database.internal" not in response.text


@pytest.mark.asyncio
async def test_admin_can_run_a_sanitized_real_deepseek_probe(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    database = ProbeEndpointDatabaseStub()
    llm_client = DeepSeekProbeClientStub()
    app = FastAPI(version="1.2.3")
    app.state.db_client = database
    app.state.container = SimpleNamespace(llm_client=llm_client)
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/diagnostics/deepseek-probe",
            headers={**_access_header(role="admin"), "X-Trace-ID": "probe-trace"},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "READY",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "is_mock": False,
        "request_id": "probe-request",
        "trace_id": "probe-trace",
        "latency_seconds": 0.125,
    }
    assert llm_client.kwargs["venue_id"] == "venue-alpha"
    assert llm_client.kwargs["agent_id"] == "RuntimeDiagnostics"
    assert llm_client.kwargs["model"] == "deepseek-v4-flash"
    assert database.executed
    assert "private-probe-output-must-not-leak" not in response.text


@pytest.mark.asyncio
async def test_deepseek_probe_rejects_mock_evidence(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    database = ProbeEndpointDatabaseStub()
    app = FastAPI(version="1.2.3")
    app.state.db_client = database
    app.state.container = SimpleNamespace(llm_client=MockDeepSeekProbeClientStub())
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/diagnostics/deepseek-probe",
            headers=_access_header(role="admin"),
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DEEPSEEK_PROBE_FAILED"
    assert "private-probe-output-must-not-leak" not in response.text


@pytest.mark.asyncio
async def test_deepseek_probe_fails_when_success_evidence_was_not_persisted(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    database = ProbeEndpointDatabaseStub(probe_evidence_persisted=False)
    app = FastAPI(version="1.2.3")
    app.state.db_client = database
    app.state.container = SimpleNamespace(llm_client=DeepSeekProbeClientStub())
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/diagnostics/deepseek-probe",
            headers={**_access_header(role="admin"), "X-Trace-ID": "probe-trace"},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DEEPSEEK_PROBE_FAILED"
    assert any("FAILED" in parameters for _sql, parameters in database.executed)


@pytest.mark.asyncio
async def test_deepseek_probe_rejects_evidence_without_request_id(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    database = ProbeEndpointDatabaseStub(probe_request_id=None)
    app = FastAPI(version="1.2.3")
    app.state.db_client = database
    app.state.container = SimpleNamespace(llm_client=MissingRequestIdDeepSeekProbeClientStub())
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/diagnostics/deepseek-probe",
            headers={**_access_header(role="admin"), "X-Trace-ID": "probe-trace"},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DEEPSEEK_PROBE_FAILED"
    assert any("FAILED" in parameters for _sql, parameters in database.executed)


@pytest.mark.asyncio
async def test_runtime_diagnostics_is_admin_only(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "diagnostics-test-secret-with-32-characters")
    app = FastAPI()
    app.state.db_client = DiagnosticsDatabaseStub()
    app.include_router(management_router, prefix="/admin")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/diagnostics", headers=_access_header(role="manager"))
        probe_response = await client.post(
            "/admin/diagnostics/deepseek-probe",
            headers=_access_header(role="manager"),
        )

    assert response.status_code == 403
    assert probe_response.status_code == 403


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
