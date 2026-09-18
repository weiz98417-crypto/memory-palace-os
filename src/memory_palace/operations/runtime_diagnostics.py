"""Sanitized runtime readiness for the unified-agent UAT gate.

Surfaces the 模型服务 (model service) contract from CONTEXT.md: the single
generative model, its REAL llm_call_logs evidence, the daily token quota, and the
circuit breaker — never a fabricated call record.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..config.integration_readiness import REAL_WECOM_POLICY_MODE
from ..config.secrets import read_secret
from ..skills import list_skill_names
from ..tools.llm_wrapper import REQUIRED_GENERATIVE_MODEL


_AGENTS = (
    ("ContextTrigger", "context_trigger"),
    ("Router", "router"),
    ("Commander", "commander"),
    ("MemoryOps", "memory_ops"),
    ("Persona", "persona"),
    ("PersonaExtract", "persona_extract"),
    ("TodoWrite", "todo_write"),
    ("Watcher", "watcher"),
)
DEEPSEEK_DIAGNOSTIC_AGENT_ID = "RuntimeDiagnostics"
_DEEPSEEK_EVIDENCE_MAX_AGE_SECONDS = 15 * 60


async def collect_runtime_diagnostics(
    request: Any,
    db: Any,
    *,
    venue_id: str,
) -> dict[str, Any]:
    """Collect a field-whitelisted view of production dependencies and agents."""

    runtime: dict[str, dict[str, Any]] = {
        "app": {
            "status": "healthy",
            "version": str(getattr(request.app, "version", "unknown")),
            "instance_id": getattr(request.app.state, "runtime_instance_id", None),
        },
        "postgresql": await _postgresql_status(db),
        "redis": await _redis_status(getattr(request.app.state, "message_queue", None)),
        "pgvector": _pgvector_status(getattr(request.app.state, "vector_store", None)),
        "worker": _worker_status(getattr(request.app.state, "message_worker", None)),
    }
    agents, agent_coverage = await _agent_statuses(db, venue_id=venue_id)
    deepseek = await _deepseek_status(db, venue_id=venue_id)
    latest_real_call = await _latest_real_call(db, venue_id=venue_id)
    token_quota = await _token_quota_status(db, venue_id=venue_id)
    circuit_breaker = await _circuit_breaker_status(db, venue_id=venue_id)
    model_runtime = _model_runtime_status(
        deepseek=deepseek,
        latest_real_call=latest_real_call,
        token_quota=token_quota,
        circuit_breaker=circuit_breaker,
    )
    observability = _observability_status()
    wecom_simulator = await _wecom_simulator_status(db, venue_id=venue_id)
    healthy = all(component.get("status") == "healthy" for component in runtime.values())
    return {
        "status": (
            "healthy"
            if healthy
            and model_runtime["status"] == "READY"
            and agent_coverage["status"] == "healthy"
            and wecom_simulator["status"] == "SIMULATOR_READY"
            else "degraded"
        ),
        "runtime": runtime,
        "agents": agents,
        "agent_coverage": agent_coverage,
        "deepseek": deepseek,
        "model_runtime": model_runtime,
        "token_quota": token_quota,
        "circuit_breaker": circuit_breaker,
        "observability": observability,
        "channels": {
            "wecom_simulator": wecom_simulator,
            "real_wecom": {
                "status": "DISABLED_BY_POLICY",
                "policy_mode": REAL_WECOM_POLICY_MODE,
                "client_initialized": False,
                "enqueue_enabled": False,
                "delivery_enabled": False,
            },
        },
    }


async def run_deepseek_probe(
    llm_client: Any,
    db: Any,
    *,
    venue_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Run one live model connectivity probe and return only safe metadata."""

    probe_started_at = time.time()
    response = await llm_client.ask(
        system_prompt="You are a runtime connectivity probe. Reply with READY only.",
        user_prompt="Verify that the configured model can answer this request.",
        model=REQUIRED_GENERATIVE_MODEL,
        temperature=0.0,
        max_tokens=8,
        trace_id=trace_id,
        venue_id=venue_id,
        agent_id=DEEPSEEK_DIAGNOSTIC_AGENT_ID,
        agent_name=DEEPSEEK_DIAGNOSTIC_AGENT_ID,
    )
    model_name = str(getattr(response, "model_name", ""))
    is_mock = bool(getattr(response, "is_mock", False))
    if is_mock or model_name != REQUIRED_GENERATIVE_MODEL:
        raise RuntimeError("DeepSeek probe did not return live required-model evidence")
    evidence_row = await db.fetch_one(
        """
        SELECT provider, model_name, status, is_mock, request_id, trace_id, created_at
        FROM llm_call_logs
        WHERE venue_id = ?
          AND trace_id = ?
          AND agent_id = ?
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (venue_id, trace_id, DEEPSEEK_DIAGNOSTIC_AGENT_ID, probe_started_at),
    )
    evidence = _public_model_evidence(evidence_row)
    request_id = str(getattr(response, "request_id", "") or "").strip()
    if not (
        request_id
        and evidence
        and evidence["provider"] == "deepseek"
        and evidence["model_name"] == REQUIRED_GENERATIVE_MODEL
        and evidence["status"] == "SUCCEEDED"
        and evidence["is_mock"] is False
        and evidence["trace_id"] == trace_id
        and evidence["request_id"] == request_id
    ):
        raise RuntimeError("DeepSeek probe evidence was not persisted")
    return {
        "status": "READY",
        "provider": "deepseek",
        "model": model_name,
        "is_mock": False,
        "request_id": request_id,
        "trace_id": trace_id,
        "latency_seconds": float(getattr(response, "latency_seconds", 0.0) or 0.0),
    }


async def _wecom_simulator_status(db: Any, *, venue_id: str) -> dict[str, Any]:
    try:
        row = await db.fetch_one(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM users
                    WHERE venue_id = ? AND status = 'ACTIVE'
                ) AS active_user_count,
                (
                    SELECT COUNT(DISTINCT identity.user_id)
                    FROM channel_identities identity
                    JOIN users mapped_user
                      ON mapped_user.id = identity.user_id
                     AND mapped_user.venue_id = identity.venue_id
                     AND mapped_user.status = 'ACTIVE'
                    WHERE identity.venue_id = ?
                      AND identity.channel = 'WECOM_SIMULATOR'
                      AND identity.status = 'ACTIVE'
                ) AS mapped_active_user_count
            """,
            (venue_id, venue_id),
        )
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "entrypoint": "/simulator/wecom/",
            "error_type": type(exc).__name__,
        }

    active_user_count = int((row or {}).get("active_user_count") or 0)
    mapped_active_user_count = int((row or {}).get("mapped_active_user_count") or 0)
    unmapped_active_user_count = max(0, active_user_count - mapped_active_user_count)
    ready = active_user_count > 0 and unmapped_active_user_count == 0
    return {
        "status": "SIMULATOR_READY" if ready else "BLOCKED",
        "entrypoint": "/simulator/wecom/",
        "active_user_count": active_user_count,
        "mapped_active_user_count": mapped_active_user_count,
        "unmapped_active_user_count": unmapped_active_user_count,
    }


async def _latest_real_call(db: Any, *, venue_id: str) -> dict[str, Any] | None:
    try:
        row = await db.fetch_one(
            """
            /* diagnostics_latest_real_call */
            SELECT provider, model_name, status, is_mock, request_id, trace_id,
                   prompt_tokens, completion_tokens, total_tokens,
                   latency_seconds, agent_id, created_at
            FROM llm_call_logs
            WHERE venue_id = ?
              AND provider = 'deepseek'
              AND status = 'SUCCEEDED'
              AND NOT COALESCE(is_mock, FALSE)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (venue_id,),
        )
    except Exception:
        return None
    if not row:
        return None
    return {
        key: row.get(key)
        for key in (
            "provider",
            "model_name",
            "status",
            "is_mock",
            "request_id",
            "trace_id",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "latency_seconds",
            "agent_id",
            "created_at",
        )
    } | {"is_mock": bool(row.get("is_mock"))}


async def _token_quota_status(db: Any, *, venue_id: str) -> dict[str, Any]:
    try:
        limit_tokens = int(os.environ.get("SCENIC_AGENT_DAILY_TOKEN_LIMIT", "20000000"))
    except ValueError:
        limit_tokens = 20000000
    day_start = time.time() - (time.time() % 86400)
    try:
        row = await db.fetch_one(
            """
            /* diagnostics_token_usage */
            SELECT COALESCE(SUM(total_tokens), 0) AS used_tokens
            FROM llm_call_logs
            WHERE venue_id = ? AND created_at >= ?
            """,
            (venue_id, day_start),
        )
    except Exception:
        row = None
    used_tokens = max(0, int((row or {}).get("used_tokens") or 0))
    if limit_tokens <= 0:
        return {
            "status": "DISABLED",
            "limit_tokens": limit_tokens,
            "used_tokens": used_tokens,
            "remaining_tokens": None,
            "usage_percent": None,
            "window": "UTC_DAY",
        }
    remaining_tokens = max(0, limit_tokens - used_tokens)
    usage_percent = round((used_tokens / limit_tokens) * 100, 3)
    status = (
        "EXHAUSTED"
        if used_tokens >= limit_tokens
        else "WARNING"
        if usage_percent >= 80
        else "NORMAL"
    )
    return {
        "status": status,
        "limit_tokens": limit_tokens,
        "used_tokens": used_tokens,
        "remaining_tokens": remaining_tokens,
        "usage_percent": usage_percent,
        "window": "UTC_DAY",
    }


async def _circuit_breaker_status(db: Any, *, venue_id: str) -> dict[str, Any]:
    try:
        failure_threshold = max(
            1, int(os.environ.get("SCENIC_AGENT_CIRCUIT_FAILURE_THRESHOLD", "3"))
        )
    except ValueError:
        failure_threshold = 3
    try:
        recovery_timeout = max(
            1.0, float(os.environ.get("SCENIC_AGENT_CIRCUIT_RECOVERY_SECONDS", "60"))
        )
    except ValueError:
        recovery_timeout = 60.0
    try:
        rows = await db.fetch_all(
            """
            /* diagnostics_circuit */
            SELECT status, created_at
            FROM llm_call_logs
            WHERE venue_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (venue_id,),
        )
    except Exception:
        rows = []
    consecutive_failures = 0
    latest_failure_at = None
    for row in rows:
        if str(row.get("status") or "").upper() in {"FAILED", "SUCCEEDED_NO_USAGE"}:
            if str(row.get("status") or "").upper() != "FAILED":
                break
            consecutive_failures += 1
            latest_failure_at = float(row.get("created_at") or 0)
            continue
        break
    state = "CLOSED"
    retry_after_seconds = None
    if consecutive_failures >= failure_threshold and latest_failure_at:
        elapsed = max(0.0, time.time() - latest_failure_at)
        if elapsed < recovery_timeout:
            state = "OPEN"
            retry_after_seconds = round(recovery_timeout - elapsed, 3)
        else:
            state = "HALF_OPEN"
            retry_after_seconds = 0.0
    return {
        "state": state,
        "source": "llm_call_logs",
        "consecutive_failures": consecutive_failures,
        "failure_threshold": failure_threshold,
        "recovery_timeout_seconds": recovery_timeout,
        "retry_after_seconds": retry_after_seconds,
    }


def _model_runtime_status(
    *,
    deepseek: dict[str, Any],
    latest_real_call: dict[str, Any] | None,
    token_quota: dict[str, Any],
    circuit_breaker: dict[str, Any],
) -> dict[str, Any]:
    reasons = []
    if deepseek.get("status") != "READY":
        reasons.append("MODEL_NOT_READY")
    if token_quota.get("status") == "EXHAUSTED":
        reasons.append("TOKEN_QUOTA_EXHAUSTED")
    elif token_quota.get("status") == "WARNING":
        reasons.append("TOKEN_QUOTA_WARNING")
    if circuit_breaker.get("state") == "OPEN":
        reasons.append("CIRCUIT_OPEN")
    elif circuit_breaker.get("state") == "HALF_OPEN":
        reasons.append("CIRCUIT_HALF_OPEN")
    return {
        "status": "READY" if not reasons else "DEGRADED",
        "provider": deepseek.get("provider") or "deepseek",
        "model": deepseek.get("model"),
        "configured": bool(deepseek.get("configured")),
        "mock_enabled": bool(deepseek.get("mock_enabled")),
        "live_verified": bool(deepseek.get("live_verified")),
        "latest_real_call": latest_real_call,
        "degradation_reasons": reasons,
    }


def _observability_status() -> dict[str, Any]:
    ui_url = os.environ.get("JAEGER_UI_URL", "").strip() or None
    return {
        "business_evidence_source": "llm_call_logs",
        "jaeger": {
            "status": "CONFIGURED" if ui_url else "OPTIONAL_NOT_CONFIGURED",
            "ui_url": ui_url,
            "business_impact_on_unavailable": "none",
        },
    }

async def _deepseek_status(db: Any, *, venue_id: str) -> dict[str, Any]:
    model = os.environ.get("LLM_DEFAULT_MODEL", REQUIRED_GENERATIVE_MODEL)
    mock_enabled = os.environ.get("MOCK_LLM", "").strip().lower() == "true"
    try:
        api_key_configured = bool(read_secret("DEEPSEEK_API_KEY"))
    except RuntimeError:
        api_key_configured = False
    configured = api_key_configured and model == REQUIRED_GENERATIVE_MODEL

    cutoff = time.time() - _DEEPSEEK_EVIDENCE_MAX_AGE_SECONDS
    collection: dict[str, Any] = {"status": "healthy"}
    try:
        row = await db.fetch_one(
            """
            SELECT provider, model_name, status, is_mock, request_id, trace_id, created_at
            FROM llm_call_logs
            WHERE venue_id = ?
              AND agent_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (venue_id, DEEPSEEK_DIAGNOSTIC_AGENT_ID),
        )
    except Exception as exc:
        row = None
        collection = {"status": "unhealthy", "error_type": type(exc).__name__}

    evidence = _public_model_evidence(row)
    live_verified = bool(
        evidence
        and evidence["provider"] == "deepseek"
        and evidence["model_name"] == REQUIRED_GENERATIVE_MODEL
        and evidence["status"] == "SUCCEEDED"
        and evidence["is_mock"] is False
        and float(evidence["created_at"] or 0) >= cutoff
    )
    return {
        "status": (
            "READY"
            if configured and not mock_enabled and live_verified and collection["status"] == "healthy"
            else "BLOCKED"
        ),
        "provider": "deepseek",
        "model": model,
        "configured": configured,
        "mock_enabled": mock_enabled,
        "live_verified": live_verified,
        "max_evidence_age_seconds": _DEEPSEEK_EVIDENCE_MAX_AGE_SECONDS,
        "evidence_collection": collection,
        "evidence": evidence,
    }


def _public_model_evidence(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    evidence = {
        key: row.get(key)
        for key in (
            "provider",
            "model_name",
            "status",
            "is_mock",
            "request_id",
            "trace_id",
            "created_at",
        )
    }
    evidence["is_mock"] = bool(evidence["is_mock"])
    return evidence


async def _postgresql_status(db: Any) -> dict[str, str]:
    if getattr(db, "backend_name", None) != "postgresql":
        return {"status": "unhealthy"}
    try:
        row = await db.fetch_one("SELECT 1 AS ok")
    except Exception:
        row = None
    return {"status": "healthy" if row and row.get("ok") else "unhealthy"}


async def _redis_status(queue: Any) -> dict[str, Any]:
    if queue is None or not callable(getattr(queue, "diagnostics", None)):
        return {"status": "unhealthy"}
    try:
        diagnostics = await queue.diagnostics()
    except Exception:
        return {"status": "unhealthy"}
    return {
        "status": "healthy" if diagnostics.get("connected") else "unhealthy",
        **{
            key: diagnostics[key]
            for key in ("backend", "stream_depth", "pending", "lag", "dead_letter_depth")
            if key in diagnostics
        },
    }


def _pgvector_status(vector_store: Any) -> dict[str, Any]:
    if vector_store is None or not callable(getattr(vector_store, "health", None)):
        return {"status": "unhealthy"}
    try:
        health = vector_store.health()
    except Exception:
        return {"status": "unhealthy"}
    return {
        "status": "healthy" if health.get("status") == "healthy" else "unhealthy",
        **{
            key: health[key]
            for key in ("backend", "extension_version", "index_name", "model", "dimension", "device")
            if key in health
        },
    }


def _worker_status(worker: Any) -> dict[str, Any]:
    if worker is None or not callable(getattr(worker, "diagnostics", None)):
        return {"status": "unhealthy", "running": False}
    try:
        diagnostics = worker.diagnostics()
    except Exception:
        return {"status": "unhealthy", "running": False}
    return {
        "status": "healthy" if diagnostics.get("running") else "unhealthy",
        **{
            key: diagnostics[key]
            for key in ("running", "backend", "concurrency", "inflight", "started_at")
            if key in diagnostics
        },
    }


async def _agent_statuses(
    db: Any,
    *,
    venue_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    collection: dict[str, Any] = {"status": "healthy"}
    try:
        rows = await db.fetch_all(
            """
            SELECT agent_id, agent_name, provider, model_name, status,
                   is_mock, request_id, trace_id, created_at
            FROM (
                SELECT agent_id, agent_name, provider, model_name, status,
                       is_mock, request_id, trace_id, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY COALESCE(NULLIF(agent_id, ''), agent_name)
                           ORDER BY created_at DESC
                       ) AS evidence_rank
                FROM llm_call_logs
                WHERE venue_id = ?
                  AND provider = 'deepseek'
                  AND model_name = ?
                  AND status = 'SUCCEEDED'
                  AND NOT COALESCE(is_mock, FALSE)
            ) latest
            WHERE evidence_rank = 1
            """,
            (venue_id, REQUIRED_GENERATIVE_MODEL),
        )
    except Exception as exc:
        rows = []
        collection = {"status": "unhealthy", "error_type": type(exc).__name__}
    latest_by_agent: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent_id = str(row.get("agent_id") or row.get("agent_name") or "")
        if agent_id and agent_id not in latest_by_agent:
            latest_by_agent[agent_id] = row

    registered_names = set(list_skill_names())
    result = []
    for agent_id, registry_name in _AGENTS:
        registered = registry_name in registered_names
        evidence_row = latest_by_agent.get(agent_id)
        evidence = None
        if evidence_row is not None:
            evidence = _public_model_evidence(evidence_row)
        status = "UNREGISTERED"
        if registered:
            status = "LIVE_VERIFIED" if evidence is not None else "REGISTERED_UNVERIFIED"
        result.append(
            {
                "id": agent_id,
                "registry_name": registry_name,
                "registered": registered,
                "status": status,
                "evidence": evidence,
            }
        )
    registered_agent_count = sum(1 for agent in result if agent["registered"])
    verified_agent_count = sum(1 for agent in result if agent["status"] == "LIVE_VERIFIED")
    collection["status"] = (
        "healthy"
        if collection["status"] == "healthy" and registered_agent_count == len(_AGENTS)
        else "unhealthy"
    )
    return result, {
        **collection,
        "registered_agent_count": registered_agent_count,
        "verified_agent_count": verified_agent_count,
        "required_agent_count": len(_AGENTS),
        "complete": verified_agent_count == len(_AGENTS),
    }
