from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.auth import create_token
from src.memory_palace.api.v1.endpoints.management import router as management_router


class PristineSnapshotStub:
    def __init__(self, *, venue_exists: bool) -> None:
        self.venue_exists = venue_exists
        self.venue_queries = 0
        self.count_queries = 0

    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "SELECT id FROM venues" in sql:
            self.venue_queries += 1
            return {"id": parameters[0]} if self.venue_exists else None
        if "COUNT(*) AS count" in sql:
            self.count_queries += 1
            count = 1 if "FROM sessions WHERE venue_id" in sql else 0
            return {"count": count}
        return None


class SnapshotDatabaseStub:
    def __init__(self, *, venue_exists: bool = True) -> None:
        self.snapshot = PristineSnapshotStub(venue_exists=venue_exists)
        self.snapshot_entries = 0

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
        raise AssertionError("UAT pristine reads must run inside read_snapshot()")

    @asynccontextmanager
    async def read_snapshot(self):
        self.snapshot_entries += 1
        yield self.snapshot


class DatabaseWithoutSnapshot:
    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "FROM users WHERE id" in sql:
            return {
                "id": parameters[0],
                "username": "admin",
                "role": "admin",
                "venue_id": "venue-alpha",
                "status": "ACTIVE",
            }
        return None


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


def _app(database) -> FastAPI:
    app = FastAPI()
    app.state.db_client = database
    app.include_router(management_router, prefix="/admin")
    return app


@pytest.mark.asyncio
async def test_uat_pristine_returns_only_counts_from_one_snapshot(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "pristine-test-secret-with-32-characters")
    database = SnapshotDatabaseStub()
    transport = httpx.ASGITransport(app=_app(database), raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/uat-pristine/venue-yueshan",
            headers=_access_header(role="admin"),
        )

    assert response.status_code == 200, response.text
    assert set(response.json()) == {"venue_id", "pristine", "process_counts"}
    assert response.json()["venue_id"] == "venue-yueshan"
    assert response.json()["pristine"] is False
    assert response.json()["process_counts"]["sessions"] == 1
    assert "master_data" not in response.text
    assert database.snapshot_entries == 1
    assert database.snapshot.venue_queries == 1
    assert database.snapshot.count_queries > 20


@pytest.mark.asyncio
async def test_uat_pristine_is_admin_only_and_returns_404_for_unknown_venue(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "pristine-test-secret-with-32-characters")
    database = SnapshotDatabaseStub(venue_exists=False)
    transport = httpx.ASGITransport(app=_app(database), raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        forbidden = await client.get(
            "/admin/uat-pristine/venue-yueshan",
            headers=_access_header(role="manager"),
        )
        missing = await client.get(
            "/admin/uat-pristine/venue-yueshan",
            headers=_access_header(role="admin"),
        )

    assert forbidden.status_code == 403
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "UAT_BASELINE_VENUE_NOT_FOUND"
    assert database.snapshot_entries == 1
    assert database.snapshot.count_queries == 0


@pytest.mark.asyncio
async def test_uat_pristine_requires_postgresql_snapshot_database(monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "pristine-test-secret-with-32-characters")
    transport = httpx.ASGITransport(
        app=_app(DatabaseWithoutSnapshot()),
        raise_app_exceptions=False,
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/uat-pristine/venue-yueshan",
            headers=_access_header(role="admin"),
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "UAT_POSTGRESQL_REQUIRED"
