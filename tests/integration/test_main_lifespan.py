from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_lifespan_uses_one_instance_id_for_recovery_and_runtime_diagnostics(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    main = importlib.import_module("main")
    monkeypatch.setattr(main, "_DEMO_MODE", False)

    class DatabaseStub:
        async def fetch_one(self, *_args, **_kwargs):
            return {"ok": 1}

        async def close(self):
            return None

    class LLMClientStub:
        def set_database(self, database):
            self.database = database

    class VectorStoreStub:
        def health(self):
            return {"status": "healthy"}

    class ContainerStub:
        def __init__(self):
            self.db_client = DatabaseStub()
            self.llm_client = LLMClientStub()
            self.vector_store = VectorStoreStub()
            self.task_graph = object()
            self.permission_engine = object()

    class QueueStub:
        _client = None

        async def close(self):
            return None

    class WorkerStub:
        _dead_letter_queue: list[dict] = []

        def __init__(self, **_kwargs):
            pass

        async def start(self):
            await asyncio.Event().wait()

        def stop(self):
            return None

        async def drain(self, *, timeout: float):
            return True

    class SchedulerStub:
        def __init__(self, **_kwargs):
            pass

        async def start(self):
            return None

        def shutdown(self):
            return None

    class HealthRegistryStub:
        def register(self, *_args, **_kwargs):
            return None

    captured_recovery: dict[str, object] = {}

    async def recover_application_runtime(_db, **kwargs):
        captured_recovery.update(kwargs)
        return {"id": "recovery-run", "trace_id": "recovery-trace", "status": "SUCCEEDED"}

    async def no_op_async(*_args, **_kwargs):
        return None

    container_module = importlib.import_module("src.memory_palace.core.container")
    queue_worker_module = importlib.import_module("src.memory_palace.core.queue_worker")
    scheduler_module = importlib.import_module("src.memory_palace.core.scheduler")
    redis_module = importlib.import_module("src.memory_palace.core.redis_queue")
    recovery_module = importlib.import_module("src.memory_palace.core.runtime_recovery")
    db_init_module = importlib.import_module("src.memory_palace.knowledge.db_init")
    auth_module = importlib.import_module("src.memory_palace.api.v1.endpoints.auth")
    health_module = importlib.import_module("src.memory_palace.core.health")
    vector_module = importlib.import_module("src.memory_palace.knowledge.vector_store")

    monkeypatch.setattr(container_module, "AppContainer", ContainerStub)
    monkeypatch.setattr(queue_worker_module, "MessageQueueWorker", WorkerStub)
    monkeypatch.setattr(queue_worker_module, "set_message_queue", lambda _queue: None)
    monkeypatch.setattr(scheduler_module, "TaskScheduler", SchedulerStub)
    monkeypatch.setattr(redis_module, "RedisStreamsQueue", QueueStub)
    monkeypatch.setattr(recovery_module, "recover_application_runtime", recover_application_runtime)
    monkeypatch.setattr(db_init_module, "init_database", no_op_async)
    monkeypatch.setattr(auth_module, "bootstrap_identity_store", no_op_async)
    monkeypatch.setattr(health_module, "get_health_registry", HealthRegistryStub)
    monkeypatch.setattr(vector_module, "close_vector_client", lambda: None)

    app = FastAPI(version="1.2.3")
    async with main.lifespan(app):
        assert app.state.runtime_instance_id
        assert captured_recovery["instance_id"] == app.state.runtime_instance_id

