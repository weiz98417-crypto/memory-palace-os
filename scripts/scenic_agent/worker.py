"""Run the Hatchet worker that executes durable scenic advice runs."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.memory_palace.incident.call_records import LLMCallLogRecorder  # noqa: E402
from src.memory_palace.incident.command import (  # noqa: E402
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from src.memory_palace.incident.model_policy import DatabaseModelPreflight  # noqa: E402
from src.memory_palace.incident.runtime import build_incident_agent_registry  # noqa: E402
from src.memory_palace.incident.telemetry import configure_tracing  # noqa: E402
from src.memory_palace.knowledge.db_init import init_database  # noqa: E402
from src.memory_palace.knowledge.postgres_client import PostgresDBClient  # noqa: E402
from src.memory_palace.scenic.advice_runs import (  # noqa: E402
    AdviceRunRepository,
    AdviceWorker,
    InMemoryAdviceQueue,
)
from src.memory_palace.scenic.advice_sink import DatabaseAdviceSink  # noqa: E402
from src.memory_palace.scenic.hatchet_workflow import build_worker  # noqa: E402
from src.memory_palace.tools.llm_wrapper import llm_client  # noqa: E402

_runtime: dict | None = None


async def build_runtime() -> dict:
    """Build the worker dependencies inside the running event loop.

    The asyncpg pool is bound to the loop that created it, so this must run in the
    loop Hatchet uses rather than in a throwaway `asyncio.run()` loop.
    """

    database = PostgresDBClient()
    await init_database(database)
    # worker 进程里的直连 LLM 调用同样受每日 token 配额约束并落 llm_call_logs
    # 证据；不挂数据库时 _enforce_daily_token_quota 会静默放行。
    llm_client.set_database(database)
    repository = AdviceRunRepository(database)
    worker = AdviceWorker(
        repository=repository,
        queue=InMemoryAdviceQueue(),
        incident_command=PydanticAIIncidentCommand(
            agent_registry=build_incident_agent_registry(),
            call_recorder=LLMCallLogRecorder(database),
            config=IncidentCommandConfig.from_env(),
            preflight=DatabaseModelPreflight(database),
        ),
        # The worker process must publish the same activity and SSE evidence the API
        # process would; a null sink would silently drop every ready signal.
        sink=DatabaseAdviceSink(database),
    )
    return {"database": database, "repository": repository, "worker": worker}


async def provide_worker() -> AdviceWorker:
    global _runtime
    if _runtime is None:
        _runtime = await build_runtime()
    return _runtime["worker"]


def main() -> None:
    tracing_provider = configure_tracing("scenic-agent-worker")
    ready_path = Path(
        os.environ.get("HATCHET_WORKER_READY_FILE", "/tmp/scenic-agent-worker.ready")
    )
    ready_path.unlink(missing_ok=True)
    try:
        worker, _client = build_worker(worker_provider=provide_worker)
        stop_monitor = threading.Event()

        def _monitor_health() -> None:
            while not stop_monitor.is_set():
                if worker.status.name == "HEALTHY":
                    if not ready_path.exists():
                        ready_path.parent.mkdir(parents=True, exist_ok=True)
                        ready_path.write_text("ready\n", encoding="utf-8")
                else:
                    ready_path.unlink(missing_ok=True)
                stop_monitor.wait(1)

        monitor = threading.Thread(target=_monitor_health, name="worker-health", daemon=True)
        monitor.start()
        try:
            worker.start()
        finally:
            stop_monitor.set()
            monitor.join()
            ready_path.unlink(missing_ok=True)
    finally:
        if tracing_provider is not None:
            tracing_provider.shutdown()


if __name__ == "__main__":
    main()
