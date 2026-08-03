import asyncio
import time

import httpx
import pytest

from tests.integration.test_mvp_business_apis import build_app, login


async def insert_push_log(database, push_id: str, status: str = "pending") -> None:
    await database.execute(
        """
        INSERT INTO push_logs (
            push_id, venue_id, from_user, raw_text, pushed_at, adoption_status
        ) VALUES (?, 'venue-alpha', 'manager', '站内告警', ?, ?)
        """,
        (push_id, time.time(), status),
    )


@pytest.mark.asyncio
async def test_push_adoption_terminal_state_cannot_return_to_pending(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    await insert_push_log(database, "push-terminal", status="adopted")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        response = await client.patch(
            "/admin/push_logs/push-terminal/adoption",
            headers=headers,
            json={"status": "pending", "notes": "不应重新打开"},
        )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "PUSH_LOG_STATE_CHANGED"
    row = await database.fetch_one(
        "SELECT adoption_status, confirmed_notes FROM push_logs WHERE push_id = ?",
        ("push-terminal",),
    )
    assert row["adoption_status"] == "adopted"
    assert row["confirmed_notes"] is None
    await database.close()


@pytest.mark.asyncio
async def test_push_adoption_concurrent_reviews_have_one_winner(tmp_path, monkeypatch):
    app, database, _, _ = await build_app(tmp_path, monkeypatch)
    await insert_push_log(database, "push-race")
    original_execute = database.execute
    review_gate = asyncio.Event()
    arrivals = 0

    async def synchronized_execute(sql, parameters=()):
        nonlocal arrivals
        if "UPDATE push_logs SET adoption_status" in sql:
            arrivals += 1
            if arrivals == 2:
                review_gate.set()
            await review_gate.wait()
        return await original_execute(sql, parameters)

    monkeypatch.setattr(database, "execute", synchronized_execute)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = await login(client, "mvp-admin", "Mvp-Admin-Password-2026")
        adopted, rejected = await asyncio.gather(
            client.patch(
                "/admin/push_logs/push-race/adoption",
                headers=headers,
                json={"status": "adopted", "notes": "已执行"},
            ),
            client.patch(
                "/admin/push_logs/push-race/adoption",
                headers=headers,
                json={"status": "rejected", "notes": "不采纳"},
            ),
        )

    responses = [adopted, rejected]
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"]["code"] == "PUSH_LOG_STATE_CHANGED"
    row = await database.fetch_one(
        "SELECT adoption_status, confirmed_notes FROM push_logs WHERE push_id = ?",
        ("push-race",),
    )
    assert row["adoption_status"] in {"adopted", "rejected"}
    audits = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM audit_logs WHERE action = ? AND resource_id = ?",
        ("PUSH_ADOPTION_UPDATED", "push-race"),
    )
    assert audits["total"] == 1
    await database.close()
