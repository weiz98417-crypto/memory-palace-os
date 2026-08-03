"""Sanitized runtime readiness for the unified-agent UAT gate."""

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
        "chromadb": _chromadb_status(getattr(request.app.state, "vector_store", None)),
        "worker": _worker_status(getattr(request.app.state, "message_worker", None)),
    }
    agents, agent_coverage = await _agent_statuses(db, venue_id=venue_id)
    deepseek = await _deepseek_status(db, venue_id=venue_id)
    wecom_simulator = await _wecom_simulator_status(db, venue_id=venue_id)
    healthy = all(component.get("status") == "healthy" for component in runtime.values())
    return {
        "status": (
            "healthy"
            if healthy
            and deepseek["status"] == "READY"
            and agent_coverage["status"] == "healthy"
            and wecom_simulator["status"] == "SIMULATOR_READY"
            else "degraded"
        ),
        "runtime": runtime,
        "agents": agents,
        "agent_coverage": agent_coverage,
        "deepseek": deepseek,
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
    *,
    venue_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Run one live model connectivity probe and return only safe metadata."""

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
    return {
        "status": "READY",
        "provider": "deepseek",
        "model": model_name,
        "is_mock": False,
        "request_id": getattr(response, "request_id", None),
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
              AND provider = 'deepseek'
              AND model_name = ?
              AND status = 'SUCCEEDED'
              AND NOT COALESCE(is_mock, FALSE)
              AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (venue_id, REQUIRED_GENERATIVE_MODEL, cutoff),
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


def _chromadb_status(vector_store: Any) -> dict[str, Any]:
    if vector_store is None or not callable(getattr(vector_store, "health", None)):
        return {"status": "unhealthy"}
    try:
        health = vector_store.health()
    except Exception:
        return {"status": "unhealthy"}
    return {
        "status": "healthy" if health.get("status") == "healthy" else "unhealthy",
        **({"backend": health["backend"]} if "backend" in health else {}),
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
    return result, {
        **collection,
        "registered_agent_count": registered_agent_count,
        "verified_agent_count": verified_agent_count,
        "required_agent_count": len(_AGENTS),
        "complete": verified_agent_count == len(_AGENTS),
    }
