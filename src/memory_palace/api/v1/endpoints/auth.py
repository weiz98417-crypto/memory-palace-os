"""Formal login, refresh, logout, and current-user endpoints."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ...auth import (
    create_token,
    decode_token,
    get_request_db,
    hash_password,
    require_auth,
    token_fingerprint,
    verify_password,
)


router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=32, max_length=4096)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., min_length=32, max_length=4096)


class UserIdentity(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    venue_id: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserIdentity


def _access_ttl() -> int:
    return int(os.environ.get("MEMORY_PALACE_ACCESS_TOKEN_TTL", "1800"))


def _refresh_ttl() -> int:
    return int(os.environ.get("MEMORY_PALACE_REFRESH_TOKEN_TTL", "604800"))


async def _audit(
    db: Any,
    *,
    venue_id: str,
    user_id: str,
    action: str,
    outcome: str,
    trace_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO audit_logs (
            venue_id, user_id, action, resource_type, resource_id,
            outcome, trace_id, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            venue_id,
            user_id,
            action,
            "auth_session",
            user_id,
            outcome,
            trace_id,
            json.dumps(metadata or {}, ensure_ascii=False),
            time.time(),
        ),
    )


async def bootstrap_identity_store(db: Any) -> None:
    """Create the first formal administrator from deployment secrets."""
    existing = await db.fetch_one("SELECT id FROM users LIMIT 1")
    if existing:
        return

    username = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    display_name = os.environ.get("ADMIN_DISPLAY_NAME", "系统管理员").strip()
    venue_id = os.environ.get("DEFAULT_VENUE_ID", "venue-hq").strip()
    venue_name = os.environ.get("DEFAULT_VENUE_NAME", "示范景区运营中心").strip()
    if not username or not venue_id or not venue_name:
        raise RuntimeError("ADMIN_USERNAME、DEFAULT_VENUE_ID 和 DEFAULT_VENUE_NAME 不能为空")
    if password.lower() in {"", "123456", "password", "change_me_in_production"}:
        raise RuntimeError("首次启动必须通过 ADMIN_PASSWORD 提供强管理员密码")

    now = time.time()
    user_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES (?, ?, 'ACTIVE', ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (venue_id, venue_name, now, now),
    )
    await db.execute(
        """
        INSERT INTO users (
            id, username, password_hash, display_name, role, venue_id,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'admin', ?, 'ACTIVE', ?, ?)
        """,
        (user_id, username, hash_password(password), display_name, venue_id, now, now),
    )
    await _audit(
        db,
        venue_id=venue_id,
        user_id=user_id,
        action="AUTH_BOOTSTRAP_ADMIN",
        outcome="SUCCEEDED",
        trace_id=uuid.uuid4().hex,
        metadata={"username": username},
    )


async def _issue_session(db: Any, user: dict[str, Any]) -> TokenResponse:
    access_token, _, _ = create_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        venue_id=user["venue_id"],
        token_type="access",
        ttl_seconds=_access_ttl(),
    )
    refresh_token, refresh_id, refresh_exp = create_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        venue_id=user["venue_id"],
        token_type="refresh",
        ttl_seconds=_refresh_ttl(),
    )
    await db.execute(
        """
        INSERT INTO refresh_tokens (
            id, user_id, venue_id, token_hash, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            refresh_id,
            user["id"],
            user["venue_id"],
            token_fingerprint(refresh_token),
            float(refresh_exp),
            time.time(),
        ),
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=_access_ttl(),
        user=UserIdentity(
            id=user["id"],
            username=user["username"],
            display_name=user.get("display_name") or user["username"],
            role=user["role"],
            venue_id=user["venue_id"],
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: Any = Depends(get_request_db)):
    trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex
    username = body.username.strip().lower()
    user = await db.fetch_one(
        """
        SELECT id, username, password_hash, display_name, role, venue_id, status
        FROM users WHERE username = ?
        """,
        (username,),
    )
    if not user or user["status"] != "ACTIVE" or not verify_password(body.password, user["password_hash"]):
        if user:
            await _audit(
                db,
                venue_id=user["venue_id"],
                user_id=user["id"],
                action="AUTH_LOGIN",
                outcome="DENIED",
                trace_id=trace_id,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTH_INVALID_CREDENTIALS",
                "message": "用户名或密码错误。",
                "trace_id": trace_id,
                "retryable": False,
                "action": "检查凭据后重试。",
            },
        )

    await db.execute(
        "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
        (time.time(), time.time(), user["id"]),
    )
    session = await _issue_session(db, user)
    await _audit(
        db,
        venue_id=user["venue_id"],
        user_id=user["id"],
        action="AUTH_LOGIN",
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    return session


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, request: Request, db: Any = Depends(get_request_db)):
    trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except (jwt.PyJWTError, RuntimeError) as exc:
        raise HTTPException(status_code=401, detail="刷新凭据无效或已过期") from exc

    user = await db.fetch_one(
        """
        SELECT id, username, display_name, role, venue_id, status
        FROM users WHERE id = ? AND venue_id = ?
        """,
        (payload["sub"], payload["venue_id"]),
    )
    if not user or user["status"] != "ACTIVE":
        raise HTTPException(status_code=401, detail="用户状态无效")

    now = time.time()
    consumed = await db.execute(
        """
        UPDATE refresh_tokens SET revoked_at = ?
        WHERE id = ?
          AND token_hash = ?
          AND user_id = ?
          AND venue_id = ?
          AND revoked_at IS NULL
          AND expires_at > ?
        """,
        (
            now,
            payload["jti"],
            token_fingerprint(body.refresh_token),
            payload["sub"],
            payload["venue_id"],
            now,
        ),
    )
    if consumed != 1:
        raise HTTPException(status_code=401, detail="刷新凭据已失效")

    session = await _issue_session(db, user)
    await _audit(
        db,
        venue_id=user["venue_id"],
        user_id=user["id"],
        action="AUTH_REFRESH",
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    return session


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db: Any = Depends(get_request_db),
):
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except (jwt.PyJWTError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail="刷新凭据无效") from exc
    if payload["sub"] != principal["user_id"] or payload["venue_id"] != principal["venue_id"]:
        raise HTTPException(status_code=403, detail="刷新凭据不属于当前用户")
    await db.execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE id = ? AND user_id = ?",
        (time.time(), payload["jti"], principal["user_id"]),
    )
    await _audit(
        db,
        venue_id=principal["venue_id"],
        user_id=principal["user_id"],
        action="AUTH_LOGOUT",
        outcome="SUCCEEDED",
        trace_id=request.headers.get("X-Trace-ID") or uuid.uuid4().hex,
    )


@router.get("/me", response_model=UserIdentity)
async def me(
    principal: dict[str, str] = Depends(require_auth),
    db: Any = Depends(get_request_db),
):
    user = await db.fetch_one(
        """
        SELECT id, username, display_name, role, venue_id
        FROM users WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'
        """,
        (principal["user_id"], principal["venue_id"]),
    )
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return UserIdentity(**user)
