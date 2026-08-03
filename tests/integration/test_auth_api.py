import asyncio

import httpx
import pytest
from fastapi import Depends, FastAPI

from src.memory_palace.api.auth import require_auth, require_roles
from src.memory_palace.api.v1.endpoints.auth import bootstrap_identity_store, router
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database


async def build_auth_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "test-jwt-secret-with-more-than-32-characters")
    monkeypatch.setenv("ADMIN_USERNAME", "mvp-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "Mvp-Admin-Password-2026")
    monkeypatch.setenv("ADMIN_DISPLAY_NAME", "交付管理员")
    monkeypatch.setenv("DEFAULT_VENUE_ID", "venue-alpha")
    monkeypatch.setenv("DEFAULT_VENUE_NAME", "云栖山景区")

    db = AsyncDBClient(tmp_path / "auth.db")
    await init_database(db)
    await bootstrap_identity_store(db)
    app = FastAPI()
    app.state.db_client = db
    app.include_router(router, prefix="/auth")

    @app.get("/principal")
    async def principal(identity: dict[str, str] = Depends(require_auth)):
        return identity

    @app.get("/admin-only")
    async def admin_only(identity: dict[str, str] = Depends(require_roles("admin"))):
        return identity

    return app, db


@pytest.mark.asyncio
async def test_login_me_refresh_and_logout_are_real_persistent_sessions(tmp_path, monkeypatch):
    app, db = await build_auth_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/auth/login",
            json={"username": "mvp-admin", "password": "Mvp-Admin-Password-2026"},
        )
        assert login.status_code == 200
        tokens = login.json()
        assert tokens["user"]["venue_id"] == "venue-alpha"
        assert tokens["user"]["role"] == "admin"

        me = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["display_name"] == "交付管理员"

        refreshed = await client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refreshed.status_code == 200
        rotated = refreshed.json()
        assert rotated["refresh_token"] != tokens["refresh_token"]

        old_refresh = await client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert old_refresh.status_code == 401

        logout = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {rotated['access_token']}"},
            json={"refresh_token": rotated["refresh_token"]},
        )
        assert logout.status_code == 204

        revoked_refresh = await client.post(
            "/auth/refresh",
            json={"refresh_token": rotated["refresh_token"]},
        )
        assert revoked_refresh.status_code == 401

    audit = await db.fetch_all("SELECT action, outcome FROM audit_logs ORDER BY created_at")
    assert ("AUTH_BOOTSTRAP_ADMIN", "SUCCEEDED") in {
        (row["action"], row["outcome"]) for row in audit
    }
    assert ("AUTH_LOGIN", "SUCCEEDED") in {
        (row["action"], row["outcome"]) for row in audit
    }
    await db.close()


@pytest.mark.asyncio
async def test_wrong_password_never_creates_refresh_token(tmp_path, monkeypatch):
    app, db = await build_auth_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={"username": "mvp-admin", "password": "incorrect-password"},
        )

    assert response.status_code == 401
    count = await db.fetch_one("SELECT COUNT(*) as count FROM refresh_tokens")
    assert count["count"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_refresh_token_concurrent_reuse_succeeds_exactly_once(tmp_path, monkeypatch):
    app, db = await build_auth_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    class RevocationBarrierDB:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self._revocation_calls = 0
            self._both_ready = asyncio.Event()

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        async def execute(self, sql, parameters=()):
            normalized = " ".join(sql.upper().split())
            if normalized.startswith("UPDATE REFRESH_TOKENS SET REVOKED_AT"):
                self._revocation_calls += 1
                if self._revocation_calls == 2:
                    self._both_ready.set()
                await asyncio.wait_for(self._both_ready.wait(), timeout=2)
            return await self._wrapped.execute(sql, parameters)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/auth/login",
            json={"username": "mvp-admin", "password": "Mvp-Admin-Password-2026"},
        )
        assert login.status_code == 200
        refresh_token = login.json()["refresh_token"]
        app.state.db_client = RevocationBarrierDB(db)

        responses = await asyncio.gather(
            client.post("/auth/refresh", json={"refresh_token": refresh_token}),
            client.post("/auth/refresh", json={"refresh_token": refresh_token}),
        )

    assert sorted(response.status_code for response in responses) == [200, 401]
    token_count = await db.fetch_one("SELECT COUNT(*) AS count FROM refresh_tokens")
    assert token_count["count"] == 2
    refresh_audits = await db.fetch_one(
        """
        SELECT COUNT(*) AS count FROM audit_logs
        WHERE action = 'AUTH_REFRESH' AND outcome = 'SUCCEEDED'
        """
    )
    assert refresh_audits["count"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_access_token_uses_current_database_identity_and_rejects_disabled_user(
    tmp_path,
    monkeypatch,
):
    app, db = await build_auth_app(tmp_path, monkeypatch)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/auth/login",
            json={"username": "mvp-admin", "password": "Mvp-Admin-Password-2026"},
        )
        assert login.status_code == 200
        access_token = login.json()["access_token"]
        user = await db.fetch_one("SELECT id FROM users WHERE username = ?", ("mvp-admin",))

        await db.execute(
            """
            INSERT INTO venues (id, name, status, created_at, updated_at)
            VALUES (?, ?, 'ACTIVE', ?, ?)
            """,
            ("venue-beta", "西溪湿地", 1.0, 1.0),
        )
        await db.execute(
            "UPDATE users SET role = ?, venue_id = ?, updated_at = ? WHERE id = ?",
            ("manager", "venue-beta", 2.0, user["id"]),
        )

        current = await client.get(
            "/principal",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert current.status_code == 200
        assert current.json()["role"] == "manager"
        assert current.json()["venue_id"] == "venue-beta"

        forbidden = await client.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "AUTH_FORBIDDEN"

        await db.execute(
            "UPDATE users SET status = 'DISABLED', updated_at = ? WHERE id = ?",
            (3.0, user["id"]),
        )
        disabled = await client.get(
            "/principal",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert disabled.status_code == 401
    assert disabled.json()["detail"]["code"] == "AUTH_REQUIRED"
    await db.close()


@pytest.mark.asyncio
async def test_api_key_is_bound_to_deployment_tenant_and_rejects_header_spoofing(monkeypatch):
    monkeypatch.setenv(
        "MEMORY_PALACE_API_KEYS",
        "venue-alpha=alpha-api-key,venue-beta=beta-api-key",
    )
    app = FastAPI()

    @app.get("/principal")
    async def principal(identity: dict[str, str] = Depends(require_auth)):
        return identity

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        bound = await client.get(
            "/principal",
            headers={"X-API-Key": "alpha-api-key"},
        )
        spoofed = await client.get(
            "/principal",
            headers={
                "X-API-Key": "alpha-api-key",
                "X-Venue-ID": "venue-beta",
            },
        )

    assert bound.status_code == 200
    assert bound.json()["venue_id"] == "venue-alpha"
    assert spoofed.status_code == 403
    assert spoofed.json()["detail"]["code"] == "AUTH_VENUE_MISMATCH"
