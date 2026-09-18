"""Hatchet-backed advice dispatcher.

The API only needs to *hand off* a durable run; the Hatchet worker owns execution. These
two classes keep that contract explicit so the in-process adapter and the durable adapter
are interchangeable at the call site.
"""

from __future__ import annotations

from typing import Any, Protocol

from .advice_runs import AdviceFinalized, AdviceRun, AdviceWorker
from .hatchet_workflow import AdviceRunInput


class AdviceDispatcher(Protocol):
    backend_name: str

    async def dispatch(self, run: AdviceRun) -> None: ...


class InProcessAdviceDispatcher:
    """Execute through the local queue/worker (native stack and tests)."""

    backend_name = "in_process"

    def __init__(self, worker: AdviceWorker) -> None:
        self._worker = worker

    async def dispatch(self, run: AdviceRun) -> None:
        await self._worker.enqueue(run)


class HatchetAdviceDispatcher:
    """Trigger the durable Hatchet workflow; Hatchet workers execute it."""

    backend_name = "hatchet"

    def __init__(self, workflow: Any) -> None:
        self._workflow = workflow
        self.dispatched: list[dict[str, Any]] = []

    async def dispatch(self, run: AdviceRun) -> None:
        payload = AdviceRunInput(
            advice_run_id=run.run_id,
            venue_id=run.venue_id,
            incident_id=run.incident_id,
        )
        self.dispatched.append(payload.model_dump())
        await self._workflow.aio_run_no_wait(payload)


def run_durable_workflow_once(worker: AdviceWorker, run: AdviceRun) -> AdviceFinalized:
    """Synchronous helper used by the CLI worker to execute one run."""

    import asyncio

    return asyncio.run(
        worker.run_run_id(venue_id=run.venue_id, run_id=run.run_id)
    )


__all__ = [
    "AdviceDispatcher",
    "HatchetAdviceDispatcher",
    "InProcessAdviceDispatcher",
    "run_durable_workflow_once",
]
