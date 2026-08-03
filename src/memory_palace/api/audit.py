"""Tenant-aware audit helpers shared by formal API endpoints."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from fastapi import Request

from ..core.sensitive_output import sanitize_public_value


def request_trace_id(request: Optional[Request] = None) -> str:
    if request is not None:
        cached = getattr(request.state, "trace_id", None)
        if cached:
            return cached
        trace_id = request.headers.get("X-Trace-ID", "").strip()
        if trace_id:
            request.state.trace_id = trace_id[:128]
            return request.state.trace_id
        request.state.trace_id = uuid.uuid4().hex
        return request.state.trace_id
    return uuid.uuid4().hex


async def write_audit(
    db: Any,
    *,
    principal: dict[str, str],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    outcome: str,
    trace_id: str,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    await db.execute(
        """
        INSERT INTO audit_logs (
            venue_id, user_id, action, resource_type, resource_id,
            outcome, trace_id, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            principal["venue_id"],
            principal["user_id"],
            action,
            resource_type,
            resource_id,
            outcome,
            trace_id,
            json.dumps(sanitize_public_value(metadata or {}), ensure_ascii=False),
            time.time(),
        ),
    )
