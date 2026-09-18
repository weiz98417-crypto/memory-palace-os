"""Hatchet workflow for one durable scenic advice run.

Hatchet owns *runtime* history only: pause/resume, retries and the durable wait for the
human decision. Business state stays in `scenic_commands` (ADR-0018), so the workflow
never becomes a second source of truth.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel

from .advice_runs import AdviceWorker

ADVICE_DECISION_EVENT_KEY = "scenic:advice:decision"
DEFAULT_DECISION_LOOKBACK = timedelta(minutes=5)
DEFAULT_EXECUTION_TIMEOUT = timedelta(minutes=15)
WORKFLOW_NAME = "scenic-agent-advice"
WORKER_NAME = "scenic-agent-worker"


class AdviceRunInput(BaseModel):
    advice_run_id: str
    venue_id: str
    incident_id: str


class AdviceDecision(BaseModel):
    decision: Literal["ADOPT", "IGNORE", "PROCEED_WITHOUT_WAITING"]
    decided_by: str
    reason_code: str | None = None
    reason_text: str | None = None


def load_hatchet_token() -> str:
    """Hatchet needs a token at client construction; read it lazily."""

    inline = os.environ.get("HATCHET_CLIENT_TOKEN", "").strip()
    if inline:
        return inline
    token_file = os.environ.get("HATCHET_CLIENT_TOKEN_FILE", "").strip()
    if token_file and os.path.exists(token_file):
        token = open(token_file, "r", encoding="utf-8-sig").read().strip()
        os.environ["HATCHET_CLIENT_TOKEN"] = token
        return token
    raise RuntimeError(
        "HATCHET_CLIENT_TOKEN or HATCHET_CLIENT_TOKEN_FILE is required to run Hatchet"
    )


def build_workflow(
    *,
    worker: AdviceWorker | None = None,
    worker_provider: Any = None,
    hatchet: Any = None,
):
    """Register the advice workflow against an injected runtime.

    `worker` is used by the API process (which only needs a client handle), while
    `worker_provider` is an async callable used by the worker process. The provider exists
    because asyncpg pools are bound to the event loop that created them: building the
    pool under `asyncio.run()` and then using it inside Hatchet's loop raises
    "another operation is in progress".
    """

    if worker is None and worker_provider is None:
        raise ValueError("build_workflow requires worker or worker_provider")

    if hatchet is None:
        from hatchet_sdk import Hatchet

        load_hatchet_token()
        hatchet = Hatchet()

    workflow = hatchet.workflow(
        name=WORKFLOW_NAME,
        input_validator=AdviceRunInput,
    )

    @workflow.durable_task(execution_timeout=DEFAULT_EXECUTION_TIMEOUT)
    async def run_advice_until_decision(
        request: AdviceRunInput, ctx: Any
    ) -> dict[str, Any]:
        active_worker = worker if worker is not None else await worker_provider()
        finalized = await active_worker.run_run_id(
            venue_id=request.venue_id, run_id=request.advice_run_id
        )
        if finalized is None:
            return {
                "advice_run_id": request.advice_run_id,
                "state": "UNKNOWN",
                "decision": None,
            }
        if finalized.state not in {"READY", "FAILED"}:
            # SUPERSEDED means a human already advanced; there is nothing to wait for.
            return {
                "advice_run_id": request.advice_run_id,
                "state": finalized.state,
                "decision": None,
            }

        decision = await ctx.aio_wait_for_event(
            ADVICE_DECISION_EVENT_KEY,
            payload_validator=AdviceDecision,
            scope=request.incident_id,
            lookback_window=DEFAULT_DECISION_LOOKBACK,
        )
        return {
            "advice_run_id": request.advice_run_id,
            "state": finalized.state,
            "decision": decision.model_dump(),
        }

    return workflow, hatchet


def build_worker(
    *,
    worker: AdviceWorker | None = None,
    worker_provider: Any = None,
    hatchet: Any = None,
):
    workflow, client = build_workflow(
        worker=worker, worker_provider=worker_provider, hatchet=hatchet
    )
    return client.worker(WORKER_NAME, workflows=[workflow]), client


__all__ = [
    "ADVICE_DECISION_EVENT_KEY",
    "AdviceDecision",
    "AdviceRunInput",
    "DEFAULT_DECISION_LOOKBACK",
    "DEFAULT_EXECUTION_TIMEOUT",
    "WORKFLOW_NAME",
    "WORKER_NAME",
    "build_worker",
    "build_workflow",
    "load_hatchet_token",
]
