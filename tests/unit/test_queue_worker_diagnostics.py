from __future__ import annotations

import asyncio

import pytest

from src.memory_palace.core.queue_worker import MessageQueueWorker


class RedisBackendStub:
    backend_name = "redis_streams"


@pytest.mark.asyncio
async def test_worker_diagnostics_distinguishes_constructed_from_running_loop() -> None:
    worker = MessageQueueWorker(
        queue=asyncio.Queue(),
        concurrency=3,
        orchestrator=object(),
        queue_backend=RedisBackendStub(),
    )

    assert worker.diagnostics() == {
        "status": "STOPPED",
        "running": False,
        "backend": "redis_streams",
        "concurrency": 3,
        "inflight": 0,
        "started_at": None,
    }

    consumer_task = asyncio.create_task(worker.start())
    await asyncio.sleep(0)

    running = worker.diagnostics()
    assert running["status"] == "RUNNING"
    assert running["running"] is True
    assert running["started_at"] is not None

    worker.stop()
    consumer_task.cancel()
    await consumer_task

    stopped = worker.diagnostics()
    assert stopped["status"] == "STOPPED"
    assert stopped["running"] is False
