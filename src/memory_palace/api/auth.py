"""Authentication, password hashing, and tenant-aware request dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
import uuid
from typing import Any, Callable, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from ..core.tenant import set_venue_id


security = HTTPBearer(auto_error=False)
ALLOWED_ROLES = {"admin", "manager", "operator", "api"}
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a per-password random salt."""
    if not 8 <= len(password) <= 128:
        raise ValueError("密码长度必须为 8-128 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password without exposing parsing or timing details."""
    try:
        algorithm, n_value, r_value, p_value, salt_value, digest_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _jwt_secret() -> str:
    secret = os.environ.get("MEMORY_PALACE_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("MEMORY_PALACE_JWT_SECRET 必须至少 32 个字符")
    return secret


def create_token(
    *,
    user_id: str,
    username: str,
    role: str,
    venue_id: str,
    token_type: str,
    ttl_seconds: int,
    token_id: Optional[str] = None,
) -> tuple[str, str, int]:
    """Create a signed access or refresh JWT."""
    now = int(time.time())
    jti = token_id or uuid.uuid4().hex
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "venue_id": venue_id,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
        "iss": "memory-palace-os",
        "aud": "memory-palace-client",
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm="HS256")
    return token, jti, payload["exp"]


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    """Decode and validate a signed JWT and its required claims."""
    payload = jwt.decode(
        token,
        _jwt_secret(),
        algorithms=["HS256"],
        audience="memory-palace-client",
        issuer="memory-palace-os",
        options={"require": ["sub", "role", "venue_id", "type", "jti", "exp"]},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    if payload.get("role") not in ALLOWED_ROLES:
        raise jwt.InvalidTokenError("invalid role")
    return payload


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _error(request: Request, status_code: int, code: str, message: str, action: str) -> HTTPException:
    trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "trace_id": trace_id,
            "retryable": False,
            "action": action,
        },
    )


def _api_key_principal(request: Request) -> Optional[dict[str, str]]:
    api_key = request.headers.get("X-API-Key", "")
    bound_venue_id: Optional[str] = None
    for item in os.environ.get("MEMORY_PALACE_API_KEYS", "").split(","):
        venue_id, separator, configured_key = item.strip().partition("=")
        if not separator or not venue_id or not configured_key:
            continue
        if hmac.compare_digest(api_key, configured_key):
            if bound_venue_id is not None and bound_venue_id != venue_id:
                return None
            bound_venue_id = venue_id

    if not api_key or bound_venue_id is None:
        return None
    requested_venue_id = request.headers.get("X-Venue-ID", "").strip()
    if requested_venue_id and requested_venue_id != bound_venue_id:
        raise _error(
            request,
            status.HTTP_403_FORBIDDEN,
            "AUTH_VENUE_MISMATCH",
            "API Key 无权访问请求的场地。",
            "使用与 API Key 绑定的场地重试。",
        )
    return {
        "user_id": f"api:{token_fingerprint(api_key)[:12]}",
        "username": "api-client",
        "role": "api",
        "venue_id": bound_venue_id,
        "auth_type": "api_key",
    }


async def _current_jwt_principal(
    request: Request,
    payload: dict[str, Any],
) -> Optional[dict[str, str]]:
    db = await get_request_db(request)
    user = await db.fetch_one(
        """
        SELECT id, username, role, venue_id, status
        FROM users WHERE id = ?
        """,
        (str(payload["sub"]),),
    )
    if (
        not user
        or user["status"] != "ACTIVE"
        or user["role"] not in ALLOWED_ROLES
        or not user["venue_id"]
    ):
        return None
    return {
        "user_id": str(user["id"]),
        "username": str(user["username"]),
        "role": str(user["role"]),
        "venue_id": str(user["venue_id"]),
        "auth_type": "jwt",
    }


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict[str, str]:
    """Authenticate the request and bind its tenant context."""
    principal = _api_key_principal(request)
    if principal is None and credentials:
        try:
            payload = decode_token(credentials.credentials, expected_type="access")
        except (jwt.PyJWTError, RuntimeError):
            principal = None
        else:
            principal = await _current_jwt_principal(request, payload)

    if principal is None:
        client_host = request.client.host if request.client else "unknown"
        logger.warning("Unauthorized access attempt from {}", client_host)
        raise _error(
            request,
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_REQUIRED",
            "登录状态无效或已过期。",
            "请重新登录。",
        )

    set_venue_id(principal["venue_id"])
    request.state.principal = principal
    return principal


def require_roles(*roles: str) -> Callable[..., Any]:
    """Create a dependency that authorizes one or more product roles."""
    allowed = set(roles)

    async def dependency(
        request: Request,
        principal: dict[str, str] = Depends(require_auth),
    ) -> dict[str, str]:
        if principal["role"] not in allowed:
            raise _error(
                request,
                status.HTTP_403_FORBIDDEN,
                "AUTH_FORBIDDEN",
                "当前角色无权执行此操作。",
                "请联系场地管理员调整权限。",
            )
        return principal

    return dependency


async def get_request_db(request: Request) -> Any:
    db_client = getattr(request.app.state, "db_client", None)
    if db_client is None:
        raise _error(
            request,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DATABASE_NOT_READY",
            "数据服务尚未就绪。",
            "稍后重试或联系管理员查看系统健康状态。",
        )
    return db_client
