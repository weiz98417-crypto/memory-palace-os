import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from starlette.requests import Request
from redis.exceptions import TimeoutError as RedisTimeoutError
import yaml

from src.memory_palace.config.config_manager import ConfigManager
from src.memory_palace.core.redis_queue import RedisStreamsQueue
from src.memory_palace.knowledge.vector_store import PalaceVectorStore
from src.memory_palace.tools.db_client import _resolve_database_uri


def test_config_override_logs_redact_sensitive_values():
    assert ConfigManager._format_override_value("jwt.secret", "sensitive") == "<redacted>"
    assert ConfigManager._format_override_value("provider.api.key", "sensitive") == "<redacted>"
    assert ConfigManager._format_override_value("llm.default.model", "deepseek-v4-flash") == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_redis_block_timeout_is_treated_as_empty_poll():
    class FakeRedis:
        def __init__(self):
            self.calls = 0

        async def xreadgroup(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RedisTimeoutError("Timeout reading from redis")
            return [
                (
                    b"memory_palace:messages",
                    [(b"1700000000000-0", {b"data": json.dumps({"msg_id": "message-1"}).encode()})],
                )
            ]

    queue = RedisStreamsQueue()
    queue._client = FakeRedis()

    message = await queue.get()

    assert message["msg_id"] == "message-1"
    assert message["_redis_msg_id"] == "1700000000000-0"
    assert queue._client.calls == 2


@pytest.mark.asyncio
async def test_redis_queue_reclaims_stale_pending_message_before_reading_new_work(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.claims = []

        async def xautoclaim(
            self,
            stream,
            group,
            consumer,
            min_idle_time,
            start_id,
            count,
        ):
            self.claims.append(
                {
                    "stream": stream,
                    "group": group,
                    "consumer": consumer,
                    "min_idle_time": min_idle_time,
                    "start_id": start_id,
                    "count": count,
                }
            )
            return [
                b"0-0",
                [
                    (
                        b"1700000000000-0",
                        {b"data": json.dumps({"msg_id": "recovered-message"}).encode()},
                    )
                ],
                [],
            ]

        async def xreadgroup(self, *args, **kwargs):
            raise AssertionError("new work must not be read before stale pending work")

    monkeypatch.setenv("REDIS_PENDING_IDLE_MS", "1250")
    queue = RedisStreamsQueue()
    queue._client = FakeRedis()

    message = await queue.get()

    assert message == {
        "msg_id": "recovered-message",
        "_redis_msg_id": "1700000000000-0",
        "_recovered": True,
    }
    assert queue._client.claims == [
        {
            "stream": "memory_palace:messages",
            "group": "mp_workers",
            "consumer": "worker_1",
            "min_idle_time": 1250,
            "start_id": "0-0",
            "count": 1,
        }
    ]


@pytest.mark.asyncio
async def test_redis_queue_diagnostics_reports_stream_pending_consumers_and_dead_letters():
    class FakeRedis:
        async def ping(self):
            return True

        async def xlen(self, stream):
            return 17 if stream == "memory_palace:messages" else 2

        async def xpending(self, stream, group):
            assert stream == "memory_palace:messages"
            assert group == "mp_workers"
            return {
                "pending": 3,
                "min": b"1700000000000-0",
                "max": b"1700000000002-0",
                "consumers": [{"name": b"worker_1", "pending": 3}],
            }

        async def xinfo_groups(self, stream):
            assert stream == "memory_palace:messages"
            return [{"name": b"mp_workers", "consumers": 1, "pending": 3, "lag": 5}]

        async def xinfo_consumers(self, stream, group):
            assert stream == "memory_palace:messages"
            assert group == "mp_workers"
            return [{"name": b"worker_1", "pending": 3, "idle": 250}]

    queue = RedisStreamsQueue()
    queue._client = FakeRedis()

    diagnostics = await queue.diagnostics()

    assert diagnostics == {
        "backend": "redis_streams",
        "connected": True,
        "stream": "memory_palace:messages",
        "group": "mp_workers",
        "stream_depth": 17,
        "pending": 3,
        "lag": 5,
        "consumers": [{"name": "worker_1", "pending": 3, "idle_ms": 250}],
        "dead_letter_stream": "memory_palace:dead_letter",
        "dead_letter_depth": 2,
    }


@pytest.mark.asyncio
async def test_redis_queue_depth_reports_work_backlog_not_stream_history():
    class FakeRedis:
        async def xpending(self, stream, group):
            assert stream == "memory_palace:messages"
            assert group == "mp_workers"
            return {"pending": 3}

        async def xinfo_groups(self, stream):
            assert stream == "memory_palace:messages"
            return [{"name": b"mp_workers", "lag": 5}]

        async def xlen(self, stream):
            raise AssertionError("completed stream history is not queue backlog")

    queue = RedisStreamsQueue()
    queue._client = FakeRedis()

    assert await queue.get_depth() == 8


@pytest.mark.asyncio
async def test_redis_queue_lists_dead_letters_as_safe_business_records():
    class FakeRedis:
        async def xrevrange(self, stream, count):
            assert stream == "memory_palace:dead_letter"
            assert count == 20
            return [
                (
                    b"1700000000500-0",
                    {
                        b"data": json.dumps(
                            {
                                "msg_id": "message-7",
                                "venue_id": "venue-alpha",
                                "content": "东门游客跌倒",
                                "_redis_msg_id": "1700000000000-0",
                            },
                            ensure_ascii=False,
                        ).encode(),
                        b"error": "模型连续超时".encode(),
                        b"retries": b"3",
                    },
                )
            ]

    queue = RedisStreamsQueue()
    queue._client = FakeRedis()

    dead_letters = await queue.list_dead_letters()

    assert dead_letters == [
        {
            "id": "1700000000500-0",
            "created_at_ms": 1700000000500,
            "message": {
                "msg_id": "message-7",
                "venue_id": "venue-alpha",
                "content": "东门游客跌倒",
            },
            "error": "模型连续超时",
            "retries": 3,
        }
    ]


@pytest.mark.asyncio
async def test_redis_queue_retries_dead_letter_once_with_clean_payload():
    class FakeRedis:
        def __init__(self):
            self.requeued_payload = None

        async def xrange(self, stream, min, max, count):
            assert stream == "memory_palace:dead_letter"
            assert min == max == "1700000000500-0"
            assert count == 1
            return [
                (
                    b"1700000000500-0",
                    {
                        b"data": json.dumps(
                            {
                                "msg_id": "message-7",
                                "venue_id": "venue-alpha",
                                "content": "东门游客跌倒",
                                "_redis_msg_id": "1700000000000-0",
                                "_retries": 3,
                            },
                            ensure_ascii=False,
                        ).encode(),
                    },
                )
            ]

        async def eval(self, script, number_of_keys, *args):
            assert "XADD" in script and "XDEL" in script
            assert number_of_keys == 3
            assert args[:3] == (
                "memory_palace:messages",
                "memory_palace:dead_letter",
                "memory_palace:dead_letter_retry:1700000000500-0",
            )
            self.requeued_payload = json.loads(args[3])
            assert args[4] == "1700000000500-0"
            return b"1700000000800-0"

    queue = RedisStreamsQueue()
    queue._client = FakeRedis()

    result = await queue.retry_dead_letter("1700000000500-0")

    assert result == {
        "dead_letter_id": "1700000000500-0",
        "stream_message_id": "1700000000800-0",
        "message_id": "message-7",
    }
    assert queue._client.requeued_payload["_retries"] == 0
    assert "_redis_msg_id" not in queue._client.requeued_payload


@pytest.mark.asyncio
async def test_redis_queue_atomically_requeues_failed_pending_message():
    class FakeRedis:
        def __init__(self):
            self.requeued_payload = None

        async def eval(self, script, number_of_keys, *args):
            assert "XADD" in script and "XACK" in script
            assert number_of_keys == 1
            assert args[0] == "memory_palace:messages"
            self.requeued_payload = json.loads(args[1])
            assert args[2:] == ("mp_workers", "1700000000000-0")
            return b"1700000000100-0"

    queue = RedisStreamsQueue()
    queue._client = FakeRedis()

    result = await queue.retry(
        {
            "msg_id": "message-8",
            "venue_id": "venue-alpha",
            "content": "西门设备离线",
            "_redis_msg_id": "1700000000000-0",
            "_retries": 1,
        },
        "1700000000000-0",
    )

    assert result == "1700000000100-0"
    assert queue._client.requeued_payload["_retries"] == 2
    assert "_redis_msg_id" not in queue._client.requeued_payload


@pytest.mark.asyncio
async def test_redis_queue_put_deduplicates_business_message_ids():
    class FakeRedis:
        def __init__(self):
            self.results = [b"1700000000200-0", None]
            self.keys = []

        async def eval(self, script, number_of_keys, *args):
            assert "SET" in script and "NX" in script and "XADD" in script
            assert number_of_keys == 2
            assert args[0] == "memory_palace:messages"
            assert args[1].startswith("memory_palace:dedup:")
            self.keys.append(args[1])
            assert json.loads(args[2])["msg_id"] == "message-dedup-1"
            assert args[3] == 300
            return self.results.pop(0)

    queue = RedisStreamsQueue()
    queue._client = FakeRedis()
    message = {"msg_id": "message-dedup-1", "venue_id": "venue-alpha", "content": "设备告警"}

    first = await queue.put(message)
    duplicate = await queue.put(message)

    assert first is True
    assert duplicate is False
    assert queue._client.keys[0] == queue._client.keys[1]


def test_vector_store_uses_remote_chroma_in_production(monkeypatch):
    import src.memory_palace.knowledge.vector_store as vector_store_module

    captured = {}

    class FakeCollection:
        pass

    class FakeClient:
        def get_or_create_collection(self, **kwargs):
            captured["collection"] = kwargs
            return FakeCollection()

        def heartbeat(self):
            return 1700000000000000000

    def fake_http_client(*, host, port, ssl):
        captured["connection"] = {"host": host, "port": port, "ssl": ssl}
        return FakeClient()

    embedding_function = object()
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("CHROMA_HOST", "chromadb")
    monkeypatch.setenv("CHROMA_PORT", "8000")
    monkeypatch.setenv("CHROMA_SSL", "false")
    monkeypatch.setattr(vector_store_module.chromadb, "HttpClient", fake_http_client)

    store = PalaceVectorStore(embedding_function=embedding_function)

    assert store.backend_mode == "remote_http"
    assert store.health()["status"] == "healthy"
    assert captured["connection"] == {"host": "chromadb", "port": 8000, "ssl": False}
    assert captured["collection"]["embedding_function"] is embedding_function


def test_vector_store_factory_does_not_hide_production_connection_failure(monkeypatch):
    import src.memory_palace.knowledge.vector_store as vector_store_module

    class FailingVectorStore:
        def __init__(self):
            raise RuntimeError("Chroma unavailable")

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setattr(vector_store_module, "_vector_client", None)
    monkeypatch.setattr(vector_store_module, "PalaceVectorStore", FailingVectorStore)

    with pytest.raises(RuntimeError, match="Chroma unavailable"):
        vector_store_module.get_vector_client()


def test_legacy_database_manager_forbids_production_sqlite(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("DATABASE_URI", raising=False)

    with pytest.raises(RuntimeError, match="禁止回退到 SQLite"):
        _resolve_database_uri()

    monkeypatch.setenv("DATABASE_URI", "sqlite:///data/memory.db")
    with pytest.raises(RuntimeError, match="禁止使用 SQLite"):
        _resolve_database_uri()


def test_tools_package_does_not_eagerly_import_legacy_database_client():
    env = os.environ.copy()
    env["APP_ENV"] = "prod"
    env.pop("DATABASE_URI", None)
    script = (
        "import sys; "
        "import src.memory_palace.tools; "
        "assert 'src.memory_palace.tools.db_client' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_nginx_healthcheck_uses_ipv4_loopback():
    compose_path = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert compose["services"]["nginx"]["healthcheck"]["test"][-1] == "http://127.0.0.1/health"


def test_compose_passes_postgres_password_outside_database_url():
    compose_path = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    app_environment = compose["services"]["app"]["environment"]

    assert "POSTGRES_PASSWORD" not in app_environment["DATABASE_URL"]
    assert app_environment["PGPASSWORD"] == "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"


def test_compose_reads_deepseek_key_from_persistent_external_volume():
    compose_path = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    app = compose["services"]["app"]

    assert "env_file" not in app
    assert "DEEPSEEK_API_KEY" not in app["environment"]
    assert app["environment"]["DEEPSEEK_API_KEY_FILE"] == "/run/memory-palace-secrets/deepseek_api_key"
    assert "app-secrets:/run/memory-palace-secrets:ro" in app["volumes"]
    assert compose["volumes"]["app-secrets"]["external"] is True
    assert compose["volumes"]["app-secrets"]["name"] == "${MEMORY_PALACE_SECRETS_VOLUME:-memory-palace-secrets}"


def test_deepseek_secret_rotation_is_atomic_and_helper_is_isolated():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "set_deepseek_secret.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert "nginx@sha256:" in script
    assert '"--network", "none"' in script
    assert '"--read-only"' in script
    assert '"--cap-drop", "ALL"' in script
    assert "mktemp /secrets/.deepseek_api_key.XXXXXX" in script
    assert 'mv -f "$temporary_file" /secrets/deepseek_api_key' in script
    assert 'docker ps --filter "volume=$VolumeName"' in script
    assert "docker restart $containerIds" in script


def test_docker_runtime_provides_persistent_writable_embedding_cache():
    project_root = Path(__file__).resolve().parents[2]
    dockerfile = (project_root / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((project_root / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))

    assert "useradd -r -m -d /home/appuser -g appuser appuser" in dockerfile
    assert "HOME=/home/appuser" in dockerfile
    assert "embedding-cache:/home/appuser/.cache" in compose["services"]["app"]["volumes"]
    assert "embedding-cache" in compose["volumes"]


def test_wechat_client_uses_standardized_deployment_environment(monkeypatch):
    import src.memory_palace.tools.wechat_client as wechat_module

    captured = {}

    def fake_client(*, corpid, corpsecret, agentid):
        captured.update({"corpid": corpid, "corpsecret": corpsecret, "agentid": agentid})
        return object()

    for key in ("WX_CORPID", "WX_CORPSECRET", "WX_AGENTID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WECHAT_CORP_ID", "corp-standard")
    monkeypatch.setenv("WECHAT_CORP_SECRET", "secret-standard")
    monkeypatch.setenv("WECHAT_AGENT_ID", "100001")
    monkeypatch.setattr(wechat_module, "_wechat_client", None)
    monkeypatch.setattr(wechat_module, "WeChatWorkClient", fake_client)

    client = wechat_module.get_wechat_client()

    assert client is not None
    assert captured == {
        "corpid": "corp-standard",
        "corpsecret": "secret-standard",
        "agentid": 100001,
    }


@pytest.mark.asyncio
async def test_integration_status_uses_standardized_wechat_environment(monkeypatch):
    import src.memory_palace.api.v1.endpoints.management as management_module

    monkeypatch.setattr(management_module, "read_secret", lambda _: "")
    monkeypatch.setenv("WECHAT_TOKEN", "token-standard")
    monkeypatch.setenv("WECHAT_ENCODING_AES_KEY", "aes-standard")
    monkeypatch.setenv("WECHAT_CORP_ID", "corp-standard")
    monkeypatch.setenv("WECHAT_CORP_SECRET", "secret-standard")
    monkeypatch.setenv("WECHAT_AGENT_ID", "100001")
    monkeypatch.delenv("WECHAT_AES_KEY", raising=False)

    rows = await management_module._integration_status_rows("venue-standard", None)
    wechat = next(row for row in rows if row["id"] == "wechat")

    assert wechat["configured"] is True
    assert wechat["status"] == "BLOCKED"
    assert wechat["missing"] == []


@pytest.mark.asyncio
async def test_integration_status_marks_missing_optional_channels_safely_disabled(monkeypatch):
    import src.memory_palace.api.v1.endpoints.management as management_module

    monkeypatch.setattr(management_module, "read_secret", lambda _: "")
    monkeypatch.setattr(
        management_module,
        "notification_channel_readiness",
        lambda channel: {"available": False, "channel": channel, "missing": ["PROVIDER_ADAPTER"]},
    )
    for key in (
        "WECHAT_TOKEN",
        "WECHAT_ENCODING_AES_KEY",
        "WECHAT_CORP_ID",
        "WECHAT_CORP_SECRET",
        "WECHAT_AGENT_ID",
        "SMS_PROVIDER",
        "SMS_API_KEY",
        "VOICE_PROVIDER",
        "VOICE_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    rows = await management_module._integration_status_rows("venue-disabled", None)
    integrations = {row["id"]: row for row in rows}

    for integration_id in ("wechat", "sms", "voice"):
        assert integrations[integration_id]["status"] == "DISABLED_REQUIRES_CONFIG"
        assert integrations[integration_id]["safe_disabled_verified"] is True


def test_request_trace_id_is_stable_for_the_request_lifecycle():
    from src.memory_palace.api.audit import request_trace_id

    request = Request({"type": "http", "headers": []})
    first = request_trace_id(request)
    assert request_trace_id(request) == first

    supplied = Request(
        {
            "type": "http",
            "headers": [(b"x-trace-id", b"trace-from-client")],
        }
    )
    assert request_trace_id(supplied) == "trace-from-client"
    assert request_trace_id(supplied) == "trace-from-client"
