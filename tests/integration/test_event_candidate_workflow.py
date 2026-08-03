import time

import httpx
import pytest

from src.memory_palace.api.v1.endpoints import workflows
from src.memory_palace.knowledge.db_client import save_confirmed_event
from tests.integration.test_mvp_business_apis import build_app, create_user, login


@pytest.mark.asyncio
async def test_event_close_keeps_closed_state_when_candidate_generation_is_retryable(
    tmp_path,
    monkeypatch,
):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    captured = {}

    async def candidate_failure(_database, **kwargs):
        captured.update(kwargs)
        return {
            "outcome": "FAILED",
            "candidate": {
                "id": "candidate-retryable",
                "status": "DRAFT",
                "index_status": "NOT_INDEXED",
                "extraction_status": "FAILED",
                "retryable": True,
            },
            "idempotent_replay": False,
            "retryable": True,
            "extraction": {
                "status": "FAILED",
                "model": "deepseek-v4-flash",
                "trace_id": "trace-candidate-failed",
                "attempt_count": 1,
                "error": "DeepSeek 经验候选萃取失败",
            },
            "activity": None,
        }

    monkeypatch.setattr(
        workflows,
        "ensure_event_experience_candidate",
        candidate_failure,
        raising=False,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        principal = (await client.get("/auth/me", headers=admin_headers)).json()
        created = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "观光车右后轮护板松动并与制动盘间歇摩擦。",
                "event_type": "车辆故障",
                "severity": "P1",
                "from_user": principal["id"],
            },
        )
        event_id = created.json()["event_id"]
        closed = await client.post(
            f"/admin/events/{event_id}/close",
            headers=admin_headers,
            json={
                "resolution": "已更换防松螺栓并完成三轮空载低速试车，无异响且温度正常。"
            },
        )

    assert closed.status_code == 200, closed.text
    payload = closed.json()
    assert payload["closed"] is True
    assert payload["experience_candidate"]["outcome"] == "FAILED"
    assert payload["experience_candidate"]["retryable"] is True
    persisted = await database.fetch_one(
        "SELECT status, resolution FROM confirmed_events WHERE event_id = ?",
        (event_id,),
    )
    assert persisted["status"] == "CLOSED"
    assert "三轮空载低速试车" in persisted["resolution"]
    assert captured["venue_id"] == principal["venue_id"]
    assert captured["event_id"] == event_id
    assert captured["principal"]["user_id"] == principal["id"]
    await database.close()


@pytest.mark.asyncio
async def test_event_candidate_retry_enforces_roles_and_tenant_scope(
    tmp_path,
    monkeypatch,
):
    app, database, vector_store, _ = await build_app(tmp_path, monkeypatch)
    calls = []

    async def candidate_success(_database, **kwargs):
        calls.append(kwargs)
        return {
            "outcome": "CREATED",
            "candidate": {
                "id": "candidate-created",
                "status": "DRAFT",
                "index_status": "NOT_INDEXED",
                "extraction_status": "SUCCEEDED",
                "retryable": False,
            },
            "idempotent_replay": False,
            "retryable": False,
            "extraction": {
                "status": "SUCCEEDED",
                "model": "deepseek-v4-flash",
                "trace_id": "trace-candidate-created",
                "attempt_count": 1,
                "error": None,
            },
            "activity": None,
        }

    monkeypatch.setattr(
        workflows,
        "ensure_event_experience_candidate",
        candidate_success,
        raising=False,
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        principal = (await client.get("/auth/me", headers=admin_headers)).json()
        await create_user(
            client,
            admin_headers,
            username="candidate-operator",
            role="operator",
        )
        operator_headers = await login(
            client,
            "candidate-operator",
            "Strong-Password-2026",
        )
        created = await client.post(
            "/admin/events",
            headers=admin_headers,
            json={
                "raw_text": "雨后观光车轮端异响，已完成检查。",
                "event_type": "车辆故障",
                "severity": "P1",
                "from_user": principal["id"],
            },
        )
        event_id = created.json()["event_id"]
        now = time.time()
        await database.execute(
            "UPDATE confirmed_events SET status = 'CLOSED', closed_at = ?, updated_at = ? WHERE event_id = ?",
            (now, now, event_id),
        )
        await database.execute(
            "INSERT INTO venues (id, name, status, created_at, updated_at) VALUES (?, ?, 'ACTIVE', ?, ?)",
            ("venue-foreign", "其他景区", now, now),
        )
        foreign_event_id = await save_confirmed_event(
            push_id="foreign-candidate-event",
            from_user="foreign-user",
            raw_text="其他场地车辆异响。",
            event_type="车辆故障",
            severity="P1",
            context_trigger_data={},
            venue_id="venue-foreign",
            trace_id="trace-foreign-candidate",
            database=database,
            vector_client=vector_store,
        )
        await database.execute(
            "UPDATE confirmed_events SET status = 'CLOSED', closed_at = ?, updated_at = ? WHERE event_id = ?",
            (now, now, foreign_event_id),
        )

        denied = await client.post(
            f"/admin/events/{event_id}/experience-candidate/retry",
            headers=operator_headers,
        )
        foreign = await client.post(
            f"/admin/events/{foreign_event_id}/experience-candidate/retry",
            headers=admin_headers,
        )
        retried = await client.post(
            f"/admin/events/{event_id}/experience-candidate/retry",
            headers=admin_headers,
        )

    assert denied.status_code == 403
    assert foreign.status_code == 404
    assert retried.status_code == 200, retried.text
    assert retried.json()["outcome"] == "CREATED"
    assert retried.json()["candidate"]["status"] == "DRAFT"
    assert len(calls) == 1
    assert calls[0]["venue_id"] == principal["venue_id"]
    assert calls[0]["event_id"] == event_id
    await database.close()
