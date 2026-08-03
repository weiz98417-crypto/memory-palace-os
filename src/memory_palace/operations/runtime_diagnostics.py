"""Sanitized runtime readiness for the unified-agent UAT gate."""

from __future__ import annotations

import os
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
    agents = await _agent_statuses(db, venue_id=venue_id)
    verified_agent_count = sum(agent["status"] == "LIVE_VERIFIED" for agent in agents)
    model = os.environ.get("LLM_DEFAULT_MODEL", REQUIRED_GENERATIVE_MODEL)
    mock_enabled = os.environ.get("MOCK_LLM", "").strip().lower() == "true"
    try:
        api_key_configured = bool(read_secret("DEEPSEEK_API_KEY"))
    except RuntimeError:
        api_key_configured = False
    configured = api_key_configured and model == REQUIRED_GENERATIVE_MODEL
    live_verified = verified_agent_count == len(_AGENTS)
    deepseek = {
        "status": "READY" if configured and not mock_enabled and live_verified else "BLOCKED",
        "provider": "deepseek",
        "model": model,
        "configured": configured,
        "mock_enabled": mock_enabled,
        "live_verified": live_verified,
        "verified_agent_count": verified_agent_count,
        "required_agent_count": len(_AGENTS),
    }
    healthy = all(component.get("status") == "healthy" for component in runtime.values())
    return {
        "status": "healthy" if healthy and deepseek["status"] == "READY" else "degraded",
        "runtime": runtime,
        "agents": agents,
        "deepseek": deepseek,
        "channels": {
            "wecom_simulator": {
                "status": "SIMULATOR_READY",
                "entrypoint": "/simulator/wecom/",
            },
            "real_wecom": {
                "status": "DISABLED_BY_POLICY",
                "policy_mode": REAL_WECOM_POLICY_MODE,
                "client_initialized": False,
                "enqueue_enabled": False,
                "delivery_enabled": False,
            },
        },
    }


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


async def _agent_statuses(db: Any, *, venue_id: str) -> list[dict[str, Any]]:
    try:
        rows = await db.fetch_all(
            """
            SELECT agent_id, agent_name, provider, model_name, status,
                   is_mock, request_id, trace_id, created_at
            FROM llm_call_logs
            WHERE venue_id = ?
              AND provider = 'deepseek'
              AND model_name = ?
              AND status = 'SUCCEEDED'
              AND NOT COALESCE(is_mock, FALSE)
            ORDER BY created_at DESC
            """,
            (venue_id, REQUIRED_GENERATIVE_MODEL),
        )
    except Exception:
        rows = []
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
            evidence = {
                key: evidence_row.get(key)
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
    return result
