"""Hatchet worker for the ticket-08 scenic Agent prototype."""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Literal

from hatchet_sdk import DurableContext, Hatchet
from pydantic import BaseModel

from .contracts import PrototypeRequest
from .db import PrototypeDB, secret_from_env
from .runtime import PydanticAIPrototypeCommand
from .telemetry import configure_tracing


APPROVAL_EVENT_KEY = "scenic:advice:decision"


class ApprovalDecision(BaseModel):
    decision: Literal["ADOPT", "IGNORE", "PROCEED_WITHOUT_WAITING"]
    decided_by: str
    reason: str | None = None


def _load_hatchet_token() -> None:
    if os.environ.get("HATCHET_CLIENT_TOKEN"):
        return
    token_file = os.environ.get("HATCHET_CLIENT_TOKEN_FILE", "/tokens/worker")
    if token_file and os.path.exists(token_file):
        os.environ["HATCHET_CLIENT_TOKEN"] = open(token_file, "r", encoding="utf-8-sig").read().strip()


_load_hatchet_token()

hatchet = Hatchet()
workflow = hatchet.workflow(
    name="scenic-agent-prototype",
    input_validator=PrototypeRequest,
)


def _db_from_env() -> PrototypeDB:
    return PrototypeDB(
        os.environ.get("DATABASE_URL", "postgresql://mp_user@postgres:5432/memory_palace"),
        password=os.environ.get("PGPASSWORD") or secret_from_env("POSTGRES_PASSWORD"),
    )


@workflow.durable_task(execution_timeout=timedelta(minutes=15))
async def run_incident(request: PrototypeRequest, ctx: DurableContext) -> dict:
    db = _db_from_env()
    tracer, provider = configure_tracing()
    try:
        command = PydanticAIPrototypeCommand()
        result = await command.execute(request, db=db, tracer=tracer)
        await db.append_activity(
            venue_id=request.venue_id,
            event_id=request.event_id,
            activity_type="ADVICE_READY",
            payload={
                "advice_run_id": request.incident_id,
                "summary": result.memory_ops.advice,
                "evidence_status": result.memory_ops.evidence_status,
                "citations": [citation.model_dump() for citation in result.memory_ops.citations],
                "call_refs": result.call_record_ids,
                "tei_evidence": result.tei_evidence,
            },
            trace_id=result.trace_id,
            created_by="scenic-agent-prototype",
            idempotency_key=f"advice-ready:{request.incident_id}:{request.attempt}",
        )
        decision = await ctx.aio_wait_for_event(
            APPROVAL_EVENT_KEY,
            payload_validator=ApprovalDecision,
            scope=request.incident_id,
            lookback_window=timedelta(minutes=5),
        )
        await db.append_activity(
            venue_id=request.venue_id,
            event_id=request.event_id,
            activity_type="ADVICE_DECIDED",
            payload={
                "decision": decision.decision,
                "decided_by": decision.decided_by,
                "reason": decision.reason,
                "advice_run_id": request.incident_id,
            },
            trace_id=result.trace_id,
            created_by=decision.decided_by,
            idempotency_key=f"advice-decided:{request.incident_id}:{request.attempt}",
        )
        return {
            "result": result.model_dump(),
            "decision": decision.model_dump(),
            "interrupt": {
                "paused": True,
                "paused_after_advice": True,
                "resumed_by": "hatchet_event_push",
            },
        }
    finally:
        provider.force_flush()
        await db.close()


def main() -> None:
    worker = hatchet.worker("scenic-agent-prototype-worker", workflows=[workflow])
    worker.start()


if __name__ == "__main__":
    main()
