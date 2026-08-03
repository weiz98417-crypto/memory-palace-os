import json
import time

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.auth import create_token
from src.memory_palace.api.v1.endpoints.admin import router as admin_router
from src.memory_palace.core.runtime_recovery import recover_application_runtime
from src.memory_palace.core.redis_queue import GROUP_NAME, STREAM_KEY, RedisStreamsQueue
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database


class TaskGraphStub:
    def __init__(self):
        self.reload_count = 0

    async def reload_from_db(self):
        self.reload_count += 1


class PermissionEngineStub:
    def __init__(self):
        self.reload_count = 0

    async def reload_from_db(self):
        self.reload_count += 1


class RecoverableQueueStub:
    def __init__(self):
        self.observer = None

    async def connect(self):
        return None

    async def prepare_startup_recovery(self):
        return {"status": "AVAILABLE", "pending": 3, "claimed": 3}

    def set_recovery_observer(self, observer):
        self.observer = observer


async def seed_interrupted_runtime(database):
    now = time.time()
    await database.execute(
        """
        INSERT INTO tasks (
            id, venue_id, session_id, description, status, dependencies,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, '[]', ?, ?)
        """,
        ("task-running", "venue-alpha", "session-1", "处理中任务", "RUNNING", now, now),
    )
    await database.execute(
        """
        INSERT INTO tasks (
            id, venue_id, session_id, description, status, dependencies,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, '[]', ?, ?)
        """,
        ("task-pending", "venue-alpha", "session-1", "待处理任务", "PENDING", now, now),
    )
    await database.execute(
        """
        INSERT INTO approval_requests (
            approval_id, venue_id, tool_name, args, session_id, requested_at,
            requested_by, status, execution_status
        ) VALUES (?, ?, ?, '{}', ?, ?, ?, 'APPROVED', 'EXECUTING')
        """,
        ("approval-running", "venue-alpha", "send_alert", "session-1", now, "manager-a"),
    )
    await database.execute(
        """
        INSERT INTO watcher_policies (
            id, venue_id, name, enabled, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, 1, ?, ?, ?)
        """,
        ("policy-1", "venue-alpha", "启动恢复测试", "admin-a", now, now),
    )
    await database.execute(
        """
        INSERT INTO watcher_runs (
            id, policy_id, venue_id, trigger_source, status, trace_id, started_at
        ) VALUES (?, ?, ?, 'manual', 'RUNNING', ?, ?)
        """,
        ("watcher-running", "policy-1", "venue-alpha", "watcher-trace", now),
    )


@pytest.mark.asyncio
async def test_application_recovery_persists_global_run_and_all_phase_counts(tmp_path):
    database = AsyncDBClient(tmp_path / "runtime-recovery.db")
    await init_database(database)
    await seed_interrupted_runtime(database)
    task_graph = TaskGraphStub()
    permission_engine = PermissionEngineStub()
    runtime_queue = RecoverableQueueStub()

    result = await recover_application_runtime(
        database,
        task_graph=task_graph,
        permission_engine=permission_engine,
        runtime_queue=runtime_queue,
        instance_id="app-uat-01",
        app_version="1.0.0-test",
    )

    persisted = await database.fetch_one(
        "SELECT * FROM runtime_recovery_runs WHERE id = ?",
        (result["id"],),
    )
    assert persisted is not None
    assert persisted["scope_type"] == "GLOBAL"
    assert persisted["venue_id"] == ""
    assert result["status"] == "RUNNING"
    assert persisted["status"] == "RUNNING"
    assert persisted["instance_id"] == "app-uat-01"
    assert persisted["app_version"] == "1.0.0-test"
    assert persisted["task_graph_recovered_count"] == 2
    assert persisted["task_graph_reset_count"] == 1
    assert persisted["approval_interrupted_count"] == 1
    assert persisted["watcher_interrupted_count"] == 1
    assert persisted["redis_status"] == "AVAILABLE"
    assert persisted["redis_pending_count"] == 3
    assert persisted["redis_claimed_count"] == 3
    assert persisted["redis_acked_count"] == 0
    assert persisted["completed_at"] is None
    assert persisted["trace_id"]
    assert [phase["phase"] for phase in json.loads(persisted["trace_json"])] == [
        "task_graph",
        "approvals",
        "watcher",
        "redis",
    ]
    assert task_graph.reload_count == 1
    assert permission_engine.reload_count == 1
    assert runtime_queue.observer is not None

    await runtime_queue.observer("ack", "redis-entry-1")
    after_first_ack = await database.fetch_one(
        "SELECT status, redis_acked_count, completed_at FROM runtime_recovery_runs WHERE id = ?",
        (result["id"],),
    )
    assert after_first_ack["status"] == "RUNNING"
    assert after_first_ack["redis_acked_count"] == 1
    assert after_first_ack["completed_at"] is None

    await runtime_queue.observer("ack", "redis-entry-2")
    await runtime_queue.observer("ack", "redis-entry-3")
    after_all_acks = await database.fetch_one(
        "SELECT status, redis_acked_count, completed_at, trace_json "
        "FROM runtime_recovery_runs WHERE id = ?",
        (result["id"],),
    )
    assert after_all_acks["status"] == "SUCCEEDED"
    assert after_all_acks["redis_acked_count"] == 3
    assert after_all_acks["completed_at"] is not None
    assert json.loads(after_all_acks["trace_json"])[-1] == {
        "acked_count": 3,
        "claimed_count": 3,
        "pending_count": 3,
        "phase": "redis",
        "status": "SUCCEEDED",
    }
    await database.close()


@pytest.mark.asyncio
async def test_redis_startup_recovery_claims_pending_then_observes_ack():
    class RedisClientStub:
        def __init__(self):
            self.claim_calls = []
            self.ack_calls = []
            self.claimed = False

        async def xpending(self, stream, group):
            assert (stream, group) == (STREAM_KEY, GROUP_NAME)
            return {"pending": 1}

        async def xautoclaim(self, stream, group, consumer, **kwargs):
            self.claim_calls.append((stream, group, consumer, kwargs))
            if self.claimed:
                return (b"0-0", [], [])
            self.claimed = True
            return (
                b"0-0",
                [
                    (
                        b"1700000000000-0",
                        {b"data": json.dumps({"msg_id": "message-recovered"}).encode()},
                    )
                ],
                [],
            )

        async def xack(self, stream, group, message_id):
            self.ack_calls.append((stream, group, message_id))
            return 1

    queue = RedisStreamsQueue()
    queue._client = RedisClientStub()
    events = []

    recovery = await queue.prepare_startup_recovery()
    queue.set_recovery_observer(
        lambda event, message_id: _record_queue_event(events, event, message_id)
    )
    message = await queue.get()
    await queue.ack(message["_redis_msg_id"])

    assert recovery == {"status": "AVAILABLE", "pending": 1, "claimed": 1}
    assert message == {
        "msg_id": "message-recovered",
        "_redis_msg_id": "1700000000000-0",
        "_recovered": True,
    }
    assert queue._client.claim_calls[0][3]["min_idle_time"] == 0
    assert queue._client.ack_calls == [(STREAM_KEY, GROUP_NAME, "1700000000000-0")]
    assert events == [("ack", "1700000000000-0")]


@pytest.mark.asyncio
async def test_startup_recovery_fails_closed_on_partial_or_unsupported_claim():
    class UnsupportedClaimClient:
        async def xpending(self, stream, group):
            return {"pending": 1}

    unsupported_queue = RedisStreamsQueue()
    unsupported_queue._client = UnsupportedClaimClient()
    with pytest.raises(RuntimeError, match="XAUTOCLAIM"):
        await unsupported_queue.prepare_startup_recovery()

    class PartialClaimClient:
        async def xpending(self, stream, group):
            return {"pending": 2}

        async def xautoclaim(self, stream, group, consumer, **kwargs):
            return (
                b"0-0",
                [
                    (
                        b"1700000000001-0",
                        {b"data": json.dumps({"msg_id": "only-one"}).encode()},
                    )
                ],
                [],
            )

    partial_queue = RedisStreamsQueue()
    partial_queue._client = PartialClaimClient()
    with pytest.raises(RuntimeError, match="pending messages were not fully claimed"):
        await partial_queue.prepare_startup_recovery()

    assert list(partial_queue._startup_recovery_buffer) == []
    assert partial_queue._recovered_message_ids == set()


@pytest.mark.asyncio
async def test_application_recovery_rejects_partial_queue_claim(tmp_path):
    class PartialQueueStub:
        def __init__(self):
            self.observer = None

        async def connect(self):
            return None

        async def prepare_startup_recovery(self):
            return {"status": "AVAILABLE", "pending": 2, "claimed": 1}

        def set_recovery_observer(self, observer):
            self.observer = observer

    database = AsyncDBClient(tmp_path / "partial-runtime-recovery.db")
    await init_database(database)
    runtime_queue = PartialQueueStub()

    with pytest.raises(RuntimeError, match="incomplete pending claim"):
        await recover_application_runtime(
            database,
            task_graph=TaskGraphStub(),
            permission_engine=PermissionEngineStub(),
            runtime_queue=runtime_queue,
            instance_id="app-partial-claim",
            app_version="1.0.0-test",
        )

    persisted = await database.fetch_one(
        "SELECT * FROM runtime_recovery_runs ORDER BY started_at DESC LIMIT 1"
    )
    assert persisted["status"] == "FAILED"
    assert persisted["redis_status"] == "UNAVAILABLE"
    assert runtime_queue.observer is None
    await database.close()


async def _record_queue_event(events, event, message_id):
    events.append((event, message_id))


def _auth_header(*, role, venue_id):
    token, _, _ = create_token(
        user_id=f"{role}-user",
        username=f"{role}-user",
        role=role,
        venue_id=venue_id,
        token_type="access",
        ttl_seconds=300,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_recovery_api_is_admin_only_and_never_reads_tenant_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "runtime-recovery-test-secret-more-than-32-characters")
    database = AsyncDBClient(tmp_path / "runtime-recovery-api.db")
    await init_database(database)
    now = time.time()
    await database.execute(
        """
        INSERT INTO venues (id, name, status, created_at, updated_at)
        VALUES ('venue-alpha', '测试场地', 'ACTIVE', ?, ?)
        """,
        (now, now),
    )
    for role in ("manager", "admin"):
        await database.execute(
            """
            INSERT INTO users (
                id, username, password_hash, display_name, role, venue_id,
                status, created_at, updated_at
            ) VALUES (?, ?, 'unused-test-hash', ?, ?, 'venue-alpha', 'ACTIVE', ?, ?)
            """,
            (f"{role}-user", f"{role}-user", f"{role} 测试用户", role, now, now),
        )
    await database.execute(
        """
        INSERT INTO runtime_recovery_runs (
            id, scope_type, venue_id, instance_id, app_version, status,
            trace_id, trace_json, started_at, completed_at
        ) VALUES (?, 'GLOBAL', '', ?, ?, 'SUCCEEDED', ?, '[]', ?, ?)
        """,
        ("global-run", "app-global", "1.0.0", "global-trace", now, now),
    )
    await database.execute(
        """
        INSERT INTO runtime_recovery_runs (
            id, scope_type, venue_id, instance_id, app_version, status,
            trace_id, trace_json, error_summary, started_at, completed_at
        ) VALUES (?, 'TENANT', ?, ?, ?, 'FAILED', ?, '[]', ?, ?, ?)
        """,
        (
            "tenant-run",
            "venue-beta",
            "tenant-worker",
            "1.0.0",
            "tenant-trace",
            "tenant-private-diagnostic",
            now + 1,
            now + 1,
        ),
    )
    app = FastAPI()
    app.state.db_client = database
    app.include_router(admin_router, prefix="/admin")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/admin/recovery-runs")
        manager = await client.get(
            "/admin/recovery-runs",
            headers=_auth_header(role="manager", venue_id="venue-alpha"),
        )
        admin = await client.get(
            "/admin/recovery-runs",
            headers=_auth_header(role="admin", venue_id="venue-alpha"),
        )

    assert unauthorized.status_code == 401
    assert manager.status_code == 403
    assert admin.status_code == 200, admin.text
    assert [item["id"] for item in admin.json()["recovery_runs"]] == ["global-run"]
    assert "venue_id" not in admin.json()["recovery_runs"][0]
    assert "tenant-private-diagnostic" not in admin.text
    await database.close()


@pytest.mark.asyncio
async def test_failed_recovery_persists_safe_error_without_exception_secret(tmp_path):
    class UnavailableQueueStub:
        async def connect(self):
            raise ConnectionError("redis://user:super-secret-token@redis.internal:6379")

    database = AsyncDBClient(tmp_path / "runtime-recovery-failure.db")
    await init_database(database)

    with pytest.raises(ConnectionError):
        await recover_application_runtime(
            database,
            task_graph=TaskGraphStub(),
            permission_engine=PermissionEngineStub(),
            runtime_queue=UnavailableQueueStub(),
            instance_id="app-failed-01",
            app_version="1.0.0-test",
        )

    persisted = await database.fetch_one(
        "SELECT * FROM runtime_recovery_runs ORDER BY started_at DESC LIMIT 1"
    )
    serialized = json.dumps(persisted, ensure_ascii=False)
    assert persisted["status"] == "FAILED"
    assert persisted["redis_status"] == "UNAVAILABLE"
    assert persisted["completed_at"] is not None
    assert persisted["error_summary"] == "redis recovery failed (ConnectionError)"
    assert json.loads(persisted["trace_json"])[-1] == {
        "error_type": "ConnectionError",
        "phase": "redis",
        "status": "FAILED",
    }
    assert "super-secret-token" not in serialized
    assert "redis.internal" not in serialized
    await database.close()
