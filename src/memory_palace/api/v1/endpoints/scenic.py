"""Authenticated scenic situation, commands, and SSE subscription routes."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...auth import require_auth
from ....agent_contracts.models import (
    CommandMode,
    FieldEvidence,
    IncidentSnapshot,
    KnowledgeHit,
    VerifiedKnowledge,
)
from ....incident.call_records import LLMCallLogRecorder
from ....incident.command import (
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from ....incident.contracts import IncidentCommandRequest
from ....incident.runtime import build_incident_agent_registry
from ....scenic.evaluation_runs import EvaluationRunRepository
from ....scenic.operations import (
    Actor,
    Command,
    ScenicCommandConflict,
    ScenicPermissionDenied,
)


router = APIRouter()

_INPUT_COMMANDS = {
    "PREPARE_SCENARIO",
    "CLOCK_STEP",
    "CLOCK_PLAY",
    "CLOCK_PAUSE",
    "INJECT_SIGNAL",
}


class ScenicCommandRequest(BaseModel):
    kind: str = Field(..., min_length=2, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


def _actor(principal: dict[str, str]) -> Actor:
    return Actor(
        user_id=principal["user_id"],
        username=principal["username"],
        role=principal["role"],
        venue_id=principal["venue_id"],
    )


def _operations(request: Request):
    operations = getattr(request.app.state, "scenic_operations", None)
    if operations is None:
        raise HTTPException(status_code=503, detail={"code": "SCENIC_RUNTIME_UNAVAILABLE"})
    return operations


def _raise_command_error(exc: Exception) -> None:
    if isinstance(exc, ScenicPermissionDenied):
        raise HTTPException(status_code=403, detail={"code": "SCENIC_FORBIDDEN", "message": str(exc)}) from exc
    if isinstance(exc, ScenicCommandConflict):
        raise HTTPException(status_code=409, detail={"code": "SCENIC_CONFLICT", "message": str(exc)}) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail={"code": "SCENIC_INPUT_INVALID", "message": str(exc)}) from exc
    raise exc


def _require_local_operations(request: Request, principal: dict[str, str]) -> None:
    allowed = {
        item.strip()
        for item in os.environ.get(
            "SCENIC_PREP_ALLOWED_HOSTS", "127.0.0.1,::1,localhost,testclient"
        ).split(",")
        if item.strip()
    }
    client_host = request.client.host if request.client else ""
    if principal.get("role") != "admin" or principal.get("username") != "simulation-ops":
        raise HTTPException(status_code=403, detail={"code": "SCENIC_PREP_IDENTITY_REQUIRED"})
    try:
        local_network = ipaddress.ip_address(client_host).is_loopback
    except ValueError:
        local_network = client_host in allowed
    if client_host not in allowed and not local_network:
        raise HTTPException(status_code=403, detail={"code": "SCENIC_PREP_LOCAL_ONLY"})


@router.get("/scenic/snapshot")
async def scenic_snapshot(
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
):
    return await _operations(request).snapshot(_actor(principal))


@router.get("/scenic/events")
async def scenic_events(
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    principal: dict[str, str] = Depends(require_auth),
):
    events = await _operations(request).events_since(
        _actor(principal), after_sequence=after_sequence, limit=limit
    )
    return {"events": events, "after_sequence": after_sequence}


@router.post("/scenic/commands")
async def scenic_business_command(
    body: ScenicCommandRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    principal: dict[str, str] = Depends(require_auth),
):
    if body.kind.strip().upper() in _INPUT_COMMANDS:
        raise HTTPException(status_code=403, detail={"code": "SCENIC_INPUT_CONTROLS_ARE_ISOLATED"})
    try:
        return await _operations(request).execute(
            _actor(principal), Command(body.kind, body.payload, idempotency_key)
        )
    except Exception as exc:
        _raise_command_error(exc)


@router.post("/operations/scenic/commands")
async def scenic_operations_command(
    body: ScenicCommandRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    principal: dict[str, str] = Depends(require_auth),
):
    _require_local_operations(request, principal)
    if body.kind.strip().upper() not in _INPUT_COMMANDS:
        raise HTTPException(status_code=403, detail={"code": "SCENIC_BUSINESS_ACTION_NOT_ALLOWED_HERE"})
    try:
        return await _operations(request).execute(
            _actor(principal), Command(body.kind, body.payload, idempotency_key)
        )
    except Exception as exc:
        _raise_command_error(exc)


def _incident_command(request: Request):
    """Resolve the Agent trunk; used by the incident advice entry point."""

    command = getattr(request.app.state, "incident_command", None)
    if command is not None:
        return command
    database = getattr(request.app.state, "db_client", None)
    if database is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_NOT_READY"})
    return PydanticAIIncidentCommand(
        agent_registry=build_incident_agent_registry(),
        call_recorder=LLMCallLogRecorder(database),
        config=IncidentCommandConfig.from_env(),
    )


def _knowledge_hits(incident_view: dict[str, Any]) -> list[KnowledgeHit]:
    hits: list[KnowledgeHit] = []
    for index, row in enumerate(incident_view.get("knowledge_hits") or []):
        source_type = str(row.get("source_type") or "SOP").upper()
        if source_type not in {"SOP", "CASE", "EXPERIENCE_CARD"}:
            continue
        score = float(row.get("score") or 0.0)
        hits.append(
            KnowledgeHit(
                vector_doc_id=str(row.get("vector_doc_id") or row.get("id") or index),
                source_id=str(row.get("source_id") or ""),
                source_type=source_type,
                source_label=source_type,
                title=str(row.get("title") or row.get("source_id") or ""),
                version=str(row.get("source_version") or ""),
                vector_score=min(1.0, max(0.0, score)),
                rerank_score=row.get("rerank_score"),
                excerpt=str(row.get("excerpt") or row.get("query_text") or ""),
                content_sha256=str(row.get("content_sha256") or row.get("id") or ""),
            )
        )
    return hits


def _sse(event_name: str, event_id: int, payload: dict[str, Any]) -> str:
    return (
        f"id: {event_id}\n"
        f"event: {event_name}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n\n"
    )


@router.get("/scenic/stream")
async def scenic_stream(
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    principal: dict[str, str] = Depends(require_auth),
):
    actor = _actor(principal)
    operations = _operations(request)
    try:
        cursor = max(after_sequence, int(last_event_id or 0))
    except ValueError:
        cursor = after_sequence
    bus = getattr(request.app.state, "scenic_situation_bus", None)

    async def generate():
        nonlocal cursor
        snapshot = await operations.snapshot(actor)
        latest = int(snapshot["latest_sequence"])
        if cursor == 0:
            cursor = latest
            yield _sse("snapshot", latest, snapshot)
        stream_id = "$"
        while not await request.is_disconnected():
            events = await operations.events_since(actor, after_sequence=cursor, limit=200)
            if events:
                for event in events:
                    cursor = int(event["sequence"])
                    event_type = str(event.get("event_type") or "situation")
                    event_name = event_type if event_type.startswith("ADVICE_") else "situation"
                    yield _sse(event_name, cursor, event)
                continue
            if bus is not None:
                try:
                    stream_id = await bus.wait(actor.venue_id, stream_id, timeout_ms=15000)
                except Exception:
                    await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(1.0)
            yield ": keep-alive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class EvaluationRunRequest(BaseModel):
    tier: str = Field(..., min_length=2, max_length=32)
    case_set: str = Field(..., min_length=2, max_length=120)
    results: list[dict[str, Any]] = Field(default_factory=list)
    judge_model: str | None = None
    context_source: str | None = None
    elapsed_seconds: float | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


def _evaluation_repository(request: Request) -> EvaluationRunRepository:
    database = getattr(request.app.state, "db_client", None)
    if database is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_NOT_READY"})
    return EvaluationRunRepository(database)


@router.get("/operations/scenic/evaluation-runs")
async def list_evaluation_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    tier: str | None = Query(default=None),
    principal: dict[str, str] = Depends(require_auth),
):
    """Evaluation history for the operations UI (manager/admin read-only)."""

    if principal.get("role") not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "SCENIC_EVAL_ROLE_REQUIRED"})
    runs = await _evaluation_repository(request).list_runs(
        venue_id=principal["venue_id"], tier=tier, limit=limit
    )
    return {
        "runs": [
            {
                "run_id": run.run_id,
                "tier": run.tier,
                "case_set": run.case_set,
                "case_count": run.case_count,
                "passed_count": run.passed_count,
                "failed_count": run.failed_count,
                "pass_rate": run.pass_rate,
                "judge_model": run.judge_model,
                "context_source": run.context_source,
                "elapsed_seconds": run.elapsed_seconds,
                "summary": run.summary,
                "created_at": run.created_at,
            }
            for run in runs
        ]
    }


@router.get("/operations/scenic/evaluation-runs/{run_id}")
async def get_evaluation_run(
    run_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
):
    if principal.get("role") not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail={"code": "SCENIC_EVAL_ROLE_REQUIRED"})
    runs = await _evaluation_repository(request).list_runs(
        venue_id=principal["venue_id"], limit=200
    )
    match = next((run for run in runs if run.run_id == run_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "SCENIC_EVAL_RUN_NOT_FOUND"})
    return {
        "run_id": match.run_id,
        "tier": match.tier,
        "case_set": match.case_set,
        "case_count": match.case_count,
        "passed_count": match.passed_count,
        "failed_count": match.failed_count,
        "pass_rate": match.pass_rate,
        "judge_model": match.judge_model,
        "context_source": match.context_source,
        "elapsed_seconds": match.elapsed_seconds,
        "summary": match.summary,
        "created_at": match.created_at,
        "results": match.results,
    }


@router.post("/operations/scenic/evaluation-runs")
async def record_evaluation_run(
    body: EvaluationRunRequest,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
):
    """Record an evaluation run. Local operator only: this writes evidence."""

    _require_local_operations(request, principal)
    run = await _evaluation_repository(request).record(
        venue_id=principal["venue_id"],
        tier=body.tier,
        case_set=body.case_set,
        results=body.results,
        judge_model=body.judge_model,
        context_source=body.context_source,
        elapsed_seconds=body.elapsed_seconds,
        summary=body.summary,
        run_id=body.run_id,
    )
    return {
        "run_id": run.run_id,
        "case_count": run.case_count,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "pass_rate": run.pass_rate,
        "created_at": run.created_at,
    }


@router.post("/scenic/incidents/{incident_id}/advice")
async def scenic_incident_advice(
    incident_id: str,
    request: Request,
    attempt: int = Query(default=1, ge=1),
    principal: dict[str, str] = Depends(require_auth),
):
    """Enqueue one advice run for the Agent trunk.

    The run is durable before it is queued, so a crash cannot lose the request and a
    retried `Idempotency-Key` resolves to the same run instead of a second model charge.
    """

    actor = _actor(principal)
    if actor.role not in {"manager", "admin"}:
        raise HTTPException(
            status_code=403, detail={"code": "SCENIC_ADVICE_ROLE_REQUIRED"}
        )
    operations = _operations(request)
    repository = getattr(request.app.state, "advice_repository", None)
    dispatcher = getattr(request.app.state, "advice_dispatcher", None)
    queue = getattr(request.app.state, "advice_queue", None)
    if repository is None or (dispatcher is None and queue is None):
        raise HTTPException(
            status_code=503, detail={"code": "SCENIC_ADVICE_RUNTIME_UNAVAILABLE"}
        )

    command_request, step = await _build_advice_request(
        request, operations, actor, incident_id
    )
    run, _created = await repository.create_or_get(
        venue_id=actor.venue_id,
        incident_id=incident_id,
        step=step,
        attempt=attempt,
        request=command_request,
    )
    if run.state == "PENDING":
        if dispatcher is not None:
            await dispatcher.dispatch(run)
        else:
            await queue.enqueue(
                {
                    "advice_run_id": run.run_id,
                    "venue_id": run.venue_id,
                    "incident_id": run.incident_id,
                }
            )
    await operations.advice_sink.project(
        venue_id=run.venue_id,
        incident_id=run.incident_id,
        run_id=run.run_id,
        state=run.state,
        activity_type="ADVICE_PENDING",
        payload={
            "advice_run_id": run.run_id,
            "state": run.state,
            "trace_id": command_request.trace_id,
            "step": step,
            "attempt": attempt,
        },
    )
    return {
        "advice_run_id": run.run_id,
        "incident_id": run.incident_id,
        "state": run.state,
        "trace_id": command_request.trace_id,
    }


@router.get("/scenic/incidents/{incident_id}/advice/{advice_run_id}")
async def scenic_advice_run(
    incident_id: str,
    advice_run_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
):
    actor = _actor(principal)
    repository = getattr(request.app.state, "advice_repository", None)
    if repository is None:
        raise HTTPException(
            status_code=503, detail={"code": "SCENIC_ADVICE_RUNTIME_UNAVAILABLE"}
        )
    run = await repository.get(venue_id=actor.venue_id, run_id=advice_run_id)
    if run is None or run.incident_id != incident_id:
        raise HTTPException(status_code=404, detail={"code": "SCENIC_ADVICE_RUN_NOT_FOUND"})
    return {
        "advice_run_id": run.run_id,
        "incident_id": run.incident_id,
        "state": run.state,
        "result": run.result,
        "error_type": run.error_type,
        "error_message": run.error_message,
    }


@router.post("/operations/scenic/advice-runs/process")
async def process_advice_runs(
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
):
    """Drain the advice queue once; the protected local runner uses this."""

    _require_local_operations(request, principal)
    worker = getattr(request.app.state, "advice_worker", None)
    if worker is None:
        raise HTTPException(
            status_code=503, detail={"code": "SCENIC_ADVICE_RUNTIME_UNAVAILABLE"}
        )
    processed = []
    for _ in range(20):
        finalized = await worker.run_once()
        if finalized is None:
            break
        processed.append(
            {
                "advice_run_id": finalized.run.run_id,
                "incident_id": finalized.run.incident_id,
                "state": finalized.state,
            }
        )
    return {"processed": processed}


async def _build_advice_request(request: Request, operations, actor, incident_id: str):
    incident_view = await operations.incident_view(actor, incident_id)
    incident = await operations.database.fetch_one(
        "SELECT * FROM scenic_incidents WHERE venue_id = ? AND incident_id = ?",
        (actor.venue_id, incident_id),
    )
    if not incident:
        raise HTTPException(status_code=404, detail={"code": "SCENIC_INCIDENT_NOT_FOUND"})
    event = await operations.database.fetch_one(
        "SELECT * FROM confirmed_events WHERE venue_id = ? AND event_id = ?",
        (actor.venue_id, incident["event_id"]),
    )
    step = CommandMode.ADVICE.value
    trace_id = uuid.uuid4().hex
    knowledge = VerifiedKnowledge(
        retrieval_snapshot_id=str(
            incident_view.get("retrieval_snapshot_id") or f"scenic:{incident_id}"
        ),
        sop_hits=_knowledge_hits(incident_view),
    )
    snapshot = IncidentSnapshot(
        incident_id=str(incident["incident_id"]),
        event_id=str(incident["event_id"]),
        business_id=str((event or {}).get("business_id") or incident["incident_id"]),
        venue_id=str(incident["venue_id"]),
        run_id=str(incident["run_id"]),
        lifecycle=str(incident["lifecycle"]),
        priority=str(incident["priority"]),
        title=str(incident["title"]),
        event_type=str((event or {}).get("event_type") or ""),
        raw_text=str((event or {}).get("raw_text") or incident["title"]),
        conversion_reason=str(incident["conversion_reason"]),
        occurred_at=float(incident.get("created_at") or 0.0),
    )
    field_evidence = [
        FieldEvidence(
            evidence_id=str(row["id"]),
            evidence_type=str(row["evidence_type"]),
            text=str(row.get("text_content") or ""),
            attachment_id=row.get("attachment_id"),
            submitted_by=str(row["submitted_by"]),
            submitted_at=float(row.get("recorded_at") or 0.0),
        )
        for row in incident_view.get("evidence") or []
    ]
    command_request = IncidentCommandRequest(
        mode=CommandMode.ADVICE,
        trace_id=trace_id,
        idempotency_key=f"advice:{incident_id}:{step}:1",
        attempt=1,
        incident=snapshot,
        field_evidence=field_evidence,
        knowledge=knowledge,
    )
    return command_request, step
