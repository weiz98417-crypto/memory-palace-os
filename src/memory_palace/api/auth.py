"""Authentication dependency for admin endpoints.
Supports API Key (X-API-Key header) and JWT (Authorization: Bearer).
Auto-passes in DEMO_MODE.
"""
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

security = HTTPBearer(auto_error=False)

# Load allowed keys from env (comma-separated)
_ALLOWED_API_KEYS: set[str] = set()
_raw_keys = os.environ.get("MEMORY_PALACE_API_KEYS", "")
if _raw_keys:
    _ALLOWED_API_KEYS = {k.strip() for k in _raw_keys.split(",") if k.strip()}

# JWT secret (optional)
_JWT_SECRET = os.environ.get("MEMORY_PALACE_JWT_SECRET", "")


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Authentication dependency. Pass to protected endpoints via Depends(require_auth)."""

    # Demo mode: auto-pass
    if os.environ.get("DEMO_MODE", "").lower() == "true":
        return {"user_id": "demo_admin", "role": "admin"}

    # API Key: X-API-Key header
    api_key = request.headers.get("X-API-Key", "")
    if api_key and api_key in _ALLOWED_API_KEYS:
        return {"user_id": "api", "role": "api"}

    # JWT: Authorization: Bearer <token>
    if credentials and _JWT_SECRET:
        try:
            import jwt
            payload = jwt.decode(
                credentials.credentials, _JWT_SECRET, algorithms=["HS256"]
            )
            return {"user_id": payload.get("sub", "unknown"), "role": payload.get("role", "user")}
        except Exception:
            pass

    logger.warning(f"Unauthorized access attempt from {request.client.host if request.client else 'unknown'}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized. Provide X-API-Key header or valid JWT Bearer token.",
    )
