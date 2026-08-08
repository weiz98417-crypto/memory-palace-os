from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from scripts.unified_agent_uat.evidence import EvidenceRun
from scripts.unified_agent_uat.journey import (
    UATJourneyConfig,
    UATJourneyError,
    run_uat_steps,
)


def _baseline() -> dict:
    return {
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "identity_channel": "WECOM_SIMULATOR",
            "real_wecom_enabled": False,
        },
        "scope": {
            "organization_name": "悦山文旅集团",
            "venue": {
                "id": "venue-yueshan",
                "name": "悦山景区",
                "status": "ACTIVE",
            },
        },
        "process_counts": {"sessions": 0, "message_runs": 0},
    }


def test_journey_config_loads_the_formal_uat_endpoint_and_external_admin_secret(
    tmp_path,
) -> None:
    password_file = tmp_path / "admin-password"
    password_file.write_text("formal-admin-password\n", encoding="utf-8")

    config = UATJourneyConfig.from_environment(
        {
            "MEMORY_PALACE_UAT_BASE_URL": "http://127.0.0.1:8082/",
            "ADMIN_USERNAME": "UAT-Admin",
            "ADMIN_PASSWORD_FILE": str(password_file),
            "MEMORY_PALACE_UAT_TIMEOUT_SECONDS": "45",
        }
    )

    assert config.base_url == "http://127.0.0.1:8082"
    assert config.admin_username == "uat-admin"
    assert config.admin_password == "formal-admin-password"
    assert config.timeout_seconds == 45.0
    assert "formal-admin-password" not in repr(config)


@pytest.mark.asyncio
async def test_e2e_00_records_sanitized_live_runtime_evidence(tmp_path) -> None:
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260804T120000Z-E2E00001",
        now=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
    )
    run.record_baseline(_baseline())
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/api/v1/auth/login":
            assert json.loads(request.content) == {
                "username": "uat-admin",
                "password": "admin-secret-password",
            }
            return httpx.Response(
                200,
                request=request,
                json={
                    "access_token": "must-not-be-recorded",
                    "refresh_token": "must-not-be-recorded-either",
                    "user": {
                        "id": "user-admin",
                        "username": "uat-admin",
                        "display_name": "刘海",
                        "role": "admin",
                        "venue_id": "venue-yueshan",
                    },
                },
            )
        assert request.headers["authorization"] == "Bearer must-not-be-recorded"
        if request.method == "POST" and request.url.path == "/api/v1/admin/diagnostics/deepseek-probe":
            return httpx.Response(
                200,
                request=request,
                json={
                    "status": "READY",
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "is_mock": False,
                    "request_id": "deepseek-request-1",
                    "trace_id": "trace-e2e-00",
                    "latency_seconds": 0.42,
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/admin/diagnostics":
            return httpx.Response(
                200,
                request=request,
                json={
                    "status": "healthy",
                    "runtime": {
                        name: {"status": "healthy"} for name in ("app", "postgresql", "redis", "chromadb", "worker")
                    },
                    "agents": [
                        {"id": name, "registered": True, "status": "REGISTERED_UNVERIFIED"}
                        for name in (
                            "ContextTrigger",
                            "Router",
                            "Commander",
                            "MemoryOps",
                            "Persona",
                            "PersonaExtract",
                            "TodoWrite",
                            "Watcher",
                        )
                    ],
                    "agent_coverage": {
                        "status": "healthy",
                        "registered_agent_count": 8,
                        "verified_agent_count": 0,
                        "required_agent_count": 8,
                        "complete": False,
                    },
                    "deepseek": {
                        "status": "READY",
                        "provider": "deepseek",
                        "model": "deepseek-v4-flash",
                        "configured": True,
                        "mock_enabled": False,
                        "live_verified": True,
                    },
                    "channels": {
                        "wecom_simulator": {
                            "status": "SIMULATOR_READY",
                            "entrypoint": "/simulator/wecom/",
                            "active_user_count": 7,
                            "mapped_active_user_count": 7,
                            "unmapped_active_user_count": 0,
                        },
                        "real_wecom": {
                            "status": "DISABLED_BY_POLICY",
                            "policy_mode": "WECOM_SIMULATOR_ONLY",
                            "client_initialized": False,
                            "enqueue_enabled": False,
                            "delivery_enabled": False,
                        },
                    },
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/admin/llm-calls":
            assert request.url.params["trace_id"] == "trace-e2e-00"
            return httpx.Response(
                200,
                request=request,
                json={
                    "llm_calls": [
                        {
                            "id": "llm-call-1",
                            "venue_id": "venue-yueshan",
                            "trace_id": "trace-e2e-00",
                            "agent_id": "RuntimeDiagnostics",
                            "provider": "deepseek",
                            "model_name": "deepseek-v4-flash",
                            "status": "SUCCEEDED",
                            "request_id": "deepseek-request-1",
                            "is_mock": False,
                        }
                    ]
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/admin/audit-logs":
            assert request.url.params["trace_id"] == "trace-e2e-00"
            return httpx.Response(
                200,
                request=request,
                json={
                    "audit_logs": [
                        {
                            "id": "audit-1",
                            "venue_id": "venue-yueshan",
                            "user_id": "user-admin",
                            "action": "DEEPSEEK_PROBE_RUN",
                            "resource_type": "runtime_diagnostics",
                            "resource_id": "trace-e2e-00",
                            "outcome": "SUCCEEDED",
                            "trace_id": "trace-e2e-00",
                        }
                    ]
                },
            )
        return httpx.Response(404, request=request)

    config = UATJourneyConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url=config.base_url,
    ) as client:
        recorded = await run_uat_steps(config, run, ["E2E-00"], client=client)

    assert recorded == [run.path / "steps" / "E2E-00.json"]
    step = json.loads(recorded[0].read_text(encoding="utf-8"))
    assert step["status"] == "PASSED"
    assert step["business_ids"] == {
        "venue_id": "venue-yueshan",
        "trace_id": "trace-e2e-00",
        "model_request_id": "deepseek-request-1",
    }
    assert step["model_calls"] == [
        {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "is_mock": False,
            "request_id": "deepseek-request-1",
            "trace_id": "trace-e2e-00",
            "status": "SUCCEEDED",
        }
    ]
    assert step["assertions"] and all(item["passed"] for item in step["assertions"])
    evidence_text = "\n".join(path.read_text(encoding="utf-8") for path in run.path.rglob("*.json"))
    assert "admin-secret-password" not in evidence_text
    assert "must-not-be-recorded" not in evidence_text
    assert calls == [
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/admin/diagnostics/deepseek-probe"),
        ("GET", "/api/v1/admin/diagnostics"),
        ("GET", "/api/v1/admin/llm-calls"),
        ("GET", "/api/v1/admin/audit-logs"),
    ]


@pytest.mark.asyncio
async def test_e2e_00_preserves_failed_evidence_and_stops_the_executor(tmp_path) -> None:
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260804T120500Z-E2E00BAD",
        now=datetime(2026, 8, 4, 12, 5, tzinfo=timezone.utc),
    )
    run.record_baseline(_baseline())

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/auth/login":
            return httpx.Response(
                200,
                request=request,
                json={
                    "access_token": "failed-step-token",
                    "user": {
                        "id": "user-admin",
                        "role": "admin",
                        "venue_id": "venue-yueshan",
                    },
                },
            )
        if request.method == "POST" and request.url.path == "/api/v1/admin/diagnostics/deepseek-probe":
            return httpx.Response(
                200,
                request=request,
                json={"trace_id": "trace-failed-e2e-00", "request_id": "request-failed-e2e-00"},
            )
        if request.method == "GET" and request.url.path == "/api/v1/admin/diagnostics":
            return httpx.Response(200, request=request, json={"status": "unhealthy"})
        if request.method == "GET" and request.url.path == "/api/v1/admin/llm-calls":
            return httpx.Response(200, request=request, json={"llm_calls": []})
        if request.method == "GET" and request.url.path == "/api/v1/admin/audit-logs":
            return httpx.Response(200, request=request, json={"audit_logs": []})
        return httpx.Response(404, request=request)

    config = UATJourneyConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url=config.base_url,
    ) as client:
        with pytest.raises(UATJourneyError, match="E2E-00.*FAILED"):
            await run_uat_steps(config, run, ["E2E-00"], client=client)

    step = json.loads((run.path / "steps" / "E2E-00.json").read_text(encoding="utf-8"))
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert step["status"] == "FAILED"
    assert manifest["status"] == "FAILED"
    assert manifest["steps"] == [
        {
            "id": "E2E-00",
            "status": "FAILED",
            "result": "steps/E2E-00.json",
            "failure": "failures/E2E-00.json",
            "sha256": manifest["steps"][0]["sha256"],
        }
    ]


@pytest.mark.asyncio
async def test_e2e_01_restores_server_bound_employee_and_rejects_forged_identity(tmp_path) -> None:
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260804T121500Z-E2E01001",
        now=datetime(2026, 8, 4, 12, 15, tzinfo=timezone.utc),
    )
    run.record_baseline(_baseline())
    run.record_step(
        "E2E-00",
        status="PASSED",
        evidence={
            "business_ids": {"trace_id": "trace-e2e-00"},
            "references": ["GET /api/v1/admin/diagnostics"],
            "assertions": [{"name": "运行门禁已通过", "passed": True}],
        },
    )
    session_payload = {"sessions": []}
    session_reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal session_reads
        if request.method == "POST" and request.url.path == "/api/v1/auth/login":
            return httpx.Response(
                200,
                request=request,
                json={
                    "access_token": "e2e-01-token",
                    "refresh_token": "e2e-01-refresh",
                    "user": {
                        "id": "user-admin",
                        "username": "uat-admin",
                        "display_name": "刘海",
                        "role": "admin",
                        "venue_id": "venue-yueshan",
                    },
                },
            )
        assert request.headers["authorization"] == "Bearer e2e-01-token"
        if request.method == "GET" and request.url.path == "/api/v1/channels/simulator-identities":
            return httpx.Response(
                200,
                request=request,
                json={
                    "identities": [
                        {
                            "user_id": "user-li-ming",
                            "username": "li-ming",
                            "display_name": "李明",
                            "role": "operator",
                            "venue_id": "venue-yueshan",
                            "organization_name": "悦山文旅集团",
                            "venue_name": "悦山景区",
                            "department": "东门运营组",
                            "job_title": "东门运营员",
                            "external_tenant_id": "wecom-yueshan",
                            "external_user_id": "wecom-li-ming",
                            "wecom_binding_status": "ACTIVE",
                            "status": "ACTIVE",
                        }
                    ]
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/assistant/sessions":
            if request.url.params["acting_user_id"] == "forged-user":
                return httpx.Response(
                    404,
                    request=request,
                    json={"detail": "Employee identity not found"},
                )
            assert request.url.params["acting_user_id"] == "user-li-ming"
            session_reads += 1
            return httpx.Response(200, request=request, json=session_payload)
        if request.method == "GET" and request.url.path == "/api/v1/admin/uat-pristine/venue-yueshan":
            return httpx.Response(
                200,
                request=request,
                json={
                    "venue_id": "venue-yueshan",
                    "pristine": True,
                    "process_counts": {
                        "sessions": 0,
                        "messages": 0,
                        "message_runs": 0,
                        "events": 0,
                    },
                },
            )
        return httpx.Response(404, request=request)

    config = UATJourneyConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url=config.base_url,
    ) as client:
        recorded = await run_uat_steps(config, run, ["E2E-01"], client=client)

    assert recorded == [run.path / "steps" / "E2E-01.json"]
    assert session_reads == 2
    step = json.loads(recorded[0].read_text(encoding="utf-8"))
    assert step["status"] == "PASSED"
    assert step["business_ids"] == {
        "venue_id": "venue-yueshan",
        "user_id": "user-li-ming",
    }
    assert all(item["passed"] for item in step["assertions"])
    artifacts = {
        item["name"]: json.loads((run.path / item["path"]).read_text(encoding="utf-8")) for item in step["artifacts"]
    }
    assert artifacts["forged-identity-rejection"] == {
        "status_code": 404,
        "detail": "Employee identity not found",
    }
    assert artifacts["restored-sessions"] == session_payload


@pytest.mark.asyncio
async def test_e2e_02_uploads_incident_image_once_and_restores_the_persisted_message(
    tmp_path,
) -> None:
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260804T123000Z-E2E02001",
        now=datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc),
    )
    run.record_baseline(_baseline())
    run.record_step(
        "E2E-01",
        status="PASSED",
        evidence={
            "business_ids": {"user_id": "user-li-ming"},
            "references": ["GET /api/v1/channels/simulator-identities"],
            "assertions": [{"name": "李明身份已确认", "passed": True}],
        },
    )
    attachment_path = tmp_path / "right-rear-wheel.png"
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"formal-uat-wheel-image"
    attachment_path.write_bytes(image_bytes)
    content = (
        "12号观光车刚做开园前试车，右后轮间歇性金属摩擦声，昨晚下过大雨，"
        "车上没人。我已经把车停在维修区并断电了，下一步怎么处理？"
    )
    description = "右后轮内侧有水迹，车辆已断电，现场无人受伤"
    external_message_id = "uat-20260804t123000z-e2e02001-e2e-02-message"
    external_conversation_id = "uat-20260804t123000z-e2e02001-li-ming"
    attachment = {
        "attachment_id": "attachment-e2e-02",
        "business_id": "FJ-20260804-0001",
        "name": attachment_path.name,
        "content_type": "image/png",
        "size_bytes": len(image_bytes),
        "sha256": "attachment-sha256",
        "scan_status": "PASSED",
        "scan_engine": "MVP_SIGNATURE_SCAN_V1",
        "external_ref": "/api/v1/assistant/attachments/attachment-e2e-02/content",
        "thumbnail_url": "/api/v1/assistant/attachments/attachment-e2e-02/content",
        "description": "",
        "uploaded_by": "user-li-ming",
        "uploaded_by_name": "李明",
        "created_at": 1785827400.0,
    }
    accepted = {
        "message_id": "message-e2e-02",
        "trace_id": "trace-e2e-02",
        "session_id": "session-e2e-02",
        "status": "QUEUED",
        "channel": "WECOM_SIMULATOR",
        "external_message_id": external_message_id,
        "external_conversation_id": external_conversation_id,
        "duplicate": False,
        "reply_text": None,
        "created_at": "2026-08-04T12:30:00Z",
        "identity": {
            "user_id": "user-li-ming",
            "display_name": "李明",
            "role": "operator",
            "venue_id": "venue-yueshan",
            "status": "ACTIVE",
        },
    }
    restored_attachment = {**attachment, "description": description}
    sessions = {
        "sessions": [
            {
                "session_id": "session-e2e-02",
                "user_id": "user-li-ming",
                "venue_id": "venue-yueshan",
                "channel": "WECOM_SIMULATOR",
                "external_conversation_id": external_conversation_id,
                "message_count": 1,
                "last_status": "QUEUED",
            }
        ]
    }
    history = {
        "session": sessions["sessions"][0],
        "identity": accepted["identity"],
        "messages": [
            {
                "id": "message-e2e-02:user",
                "role": "user",
                "message_id": "message-e2e-02",
                "trace_id": "trace-e2e-02",
                "session_id": "session-e2e-02",
                "channel": "WECOM_SIMULATOR",
                "content": content,
                "status": "SENT",
                "attachments": [restored_attachment],
            },
            {
                "id": "message-e2e-02:assistant",
                "role": "assistant",
                "message_id": "message-e2e-02",
                "trace_id": "trace-e2e-02",
                "session_id": "session-e2e-02",
                "channel": "WECOM_SIMULATOR",
                "content": None,
                "status": "QUEUED",
                "attachments": [],
            },
        ],
    }
    trace = {
        "trace_id": "trace-e2e-02",
        "venue_id": "venue-yueshan",
        "status": "RUNNING",
        "message_run": {
            "message_id": "message-e2e-02",
            "trace_id": "trace-e2e-02",
            "session_id": "session-e2e-02",
            "user_id": "user-li-ming",
            "venue_id": "venue-yueshan",
            "content": content,
            "status": "QUEUED",
            "channel": "WECOM_SIMULATOR",
            "external_message_id": external_message_id,
            "external_conversation_id": external_conversation_id,
        },
        "summary": {"audits": 2},
        "timeline": [
            {
                "kind": "MESSAGE",
                "status": "QUEUED",
                "resource_id": "message-e2e-02",
                "summary": content,
            },
            {
                "kind": "AUDIT",
                "status": "SUCCEEDED",
                "resource_id": "message-e2e-02",
                "summary": "MESSAGE_RUN_CREATED",
            },
            {
                "kind": "AUDIT",
                "status": "SUCCEEDED",
                "resource_id": "message-e2e-02",
                "summary": "MESSAGE_ENQUEUED",
            },
        ],
    }
    calls: list[tuple[str, str]] = []
    message_posts = 0
    history_reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal message_posts, history_reads
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/api/v1/auth/login":
            return httpx.Response(
                200,
                request=request,
                json={
                    "access_token": "e2e-02-token",
                    "refresh_token": "e2e-02-refresh",
                    "user": {
                        "id": "user-admin",
                        "username": "uat-admin",
                        "display_name": "刘海",
                        "role": "admin",
                        "venue_id": "venue-yueshan",
                    },
                },
            )
        assert request.headers["authorization"] == "Bearer e2e-02-token"
        if request.method == "GET" and request.url.path == "/api/v1/channels/simulator-identities":
            return httpx.Response(
                200,
                request=request,
                json={
                    "identities": [
                        {
                            "user_id": "user-li-ming",
                            "username": "li-ming",
                            "display_name": "李明",
                            "role": "operator",
                            "venue_id": "venue-yueshan",
                            "status": "ACTIVE",
                        }
                    ]
                },
            )
        if request.method == "POST" and request.url.path == "/api/v1/channels/simulator/attachments":
            assert request.headers["content-type"].startswith("multipart/form-data;")
            assert image_bytes in request.content
            assert b"user_id" in request.content
            assert b"user-li-ming" in request.content
            return httpx.Response(201, request=request, json={"attachment": attachment})
        if request.method == "POST" and request.url.path == "/api/v1/channels/simulator/messages":
            message_posts += 1
            body = json.loads(request.content)
            assert body == {
                "user_id": "user-li-ming",
                "content": content,
                "external_message_id": external_message_id,
                "external_conversation_id": external_conversation_id,
                "metadata": {
                    "venue_id": "forged-venue-must-be-ignored",
                    "uat_run_id": run.run_id,
                },
                "attachments": [
                    {
                        "attachment_id": "attachment-e2e-02",
                        "description": description,
                    }
                ],
            }
            return httpx.Response(
                202,
                request=request,
                json={**accepted, "duplicate": message_posts == 2},
            )
        if request.method == "GET" and request.url.path == "/api/v1/assistant/sessions":
            assert request.url.params["acting_user_id"] == "user-li-ming"
            return httpx.Response(200, request=request, json=sessions)
        if request.method == "GET" and request.url.path == "/api/v1/assistant/sessions/session-e2e-02/messages":
            assert request.url.params["acting_user_id"] == "user-li-ming"
            history_reads += 1
            return httpx.Response(200, request=request, json=history)
        if request.method == "GET" and request.url.path == "/api/v1/admin/traces/trace-e2e-02":
            return httpx.Response(200, request=request, json=trace)
        if request.method == "GET" and request.url.path == "/api/v1/admin/audit-logs":
            assert request.url.params["trace_id"] == "trace-e2e-02"
            return httpx.Response(
                200,
                request=request,
                json={
                    "audit_logs": [
                        {
                            "action": "MESSAGE_RUN_CREATED",
                            "resource_id": "message-e2e-02",
                            "outcome": "SUCCEEDED",
                            "trace_id": "trace-e2e-02",
                            "metadata": {"status": "QUEUED"},
                        },
                        {
                            "action": "MESSAGE_ENQUEUED",
                            "resource_id": "message-e2e-02",
                            "outcome": "SUCCEEDED",
                            "trace_id": "trace-e2e-02",
                            "metadata": {
                                "status": "QUEUED",
                                "stream_message_id": "1700000000200-0",
                            },
                        },
                    ]
                },
            )
        return httpx.Response(404, request=request)

    config = UATJourneyConfig(
        base_url="http://uat",
        admin_username="uat-admin",
        admin_password="admin-secret-password",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url=config.base_url,
    ) as client:
        recorded = await run_uat_steps(
            config,
            run,
            ["E2E-02"],
            client=client,
            attachment_path=attachment_path,
        )

    assert recorded == [run.path / "steps" / "E2E-02.json"]
    assert message_posts == 2
    assert history_reads == 2
    step = json.loads(recorded[0].read_text(encoding="utf-8"))
    assert step["status"] == "PASSED"
    assert step["business_ids"] == {
        "venue_id": "venue-yueshan",
        "user_id": "user-li-ming",
        "session_id": "session-e2e-02",
        "message_id": "message-e2e-02",
        "trace_id": "trace-e2e-02",
        "attachment_id": "attachment-e2e-02",
        "external_message_id": external_message_id,
    }
    assert all(item["passed"] for item in step["assertions"])
    artifacts = {
        item["name"]: json.loads((run.path / item["path"]).read_text(encoding="utf-8")) for item in step["artifacts"]
    }
    assert artifacts["accepted-message"]["duplicate"] is False
    assert artifacts["replayed-message"]["duplicate"] is True
    restored_history_artifact = artifacts["restored-history"]
    assert restored_history_artifact["session"] == history["session"]
    restored_attachment_artifact = restored_history_artifact["messages"][0]["attachments"][0]
    assert restored_attachment_artifact["attachment_id"] == "attachment-e2e-02"
    assert restored_attachment_artifact["external_ref"] == "<redacted>"
    assert restored_attachment_artifact["thumbnail_url"] == "<redacted>"
    assert artifacts["uploaded-attachment"]["external_ref"] == "<redacted>"
    assert artifacts["uploaded-attachment"]["thumbnail_url"] == "<redacted>"
    assert artifacts["trace-timeline"] == trace
    assert artifacts["enqueue-audit"]["metadata"]["stream_message_id"] == ("1700000000200-0")
