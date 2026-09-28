import pytest

from src.memory_palace.core.event_experience_candidates import (
    DeepSeekEventExperienceCandidateExtractor,
)
from src.memory_palace.tools.llm_wrapper import LLMClient, REQUIRED_GENERATIVE_MODEL
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database


def test_daily_quota_window_starts_at_local_midnight():
    from datetime import datetime

    from src.memory_palace.incident.model_policy import _day_start

    now = datetime(2026, 9, 28, 10, 0, 0).astimezone().timestamp()
    window_start = _day_start(now)

    # 窗口起点必须是当日零点（时分秒全为 0），且覆盖“零点到现在”
    start_local = datetime.fromtimestamp(window_start)
    assert (start_local.hour, start_local.minute, start_local.second) == (0, 0, 0)
    assert start_local.date() == datetime.fromtimestamp(now).date()
    assert window_start <= now < window_start + 86400
    assert window_start > now - 86400


def test_llm_client_defaults_to_required_deepseek_model(monkeypatch):
    monkeypatch.delenv("LLM_DEFAULT_MODEL", raising=False)

    client = LLMClient()

    assert REQUIRED_GENERATIVE_MODEL == "deepseek-flash"
    assert client.default_model == REQUIRED_GENERATIVE_MODEL


def test_llm_client_rejects_conflicting_model_configuration(monkeypatch):
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "gpt-4o")

    with pytest.raises(ValueError, match="deepseek-flash"):
        LLMClient()


def test_production_rejects_mock_llm(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("MOCK_LLM", "true")

    with pytest.raises(ValueError, match="MOCK_LLM"):
        LLMClient()


def test_event_candidate_generation_uses_existing_persona_extract_agent():
    assert DeepSeekEventExperienceCandidateExtractor.model_name == REQUIRED_GENERATIVE_MODEL
    assert DeepSeekEventExperienceCandidateExtractor.agent_name == "PersonaExtract"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "not-json"])
async def test_json_parser_rejects_unusable_model_output(content, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    client = LLMClient()

    with pytest.raises(ValueError, match="JSON"):
        await client.parse_json(content, trace_id="trace-invalid-json")


@pytest.mark.asyncio
async def test_production_rejects_mock_llm_enabled_after_client_initialization(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    client = LLMClient()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MOCK_LLM", "true")

    with pytest.raises(ValueError, match="MOCK_LLM"):
        await client.ask(system_prompt="test", user_prompt="test")


@pytest.mark.asyncio
async def test_mock_call_is_explicitly_recorded_for_non_production_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MOCK_LLM", "true")
    db = AsyncDBClient(tmp_path / "llm-evidence.db")
    await init_database(db)
    client = LLMClient()
    client.set_database(db)

    response = await client.ask(
        system_prompt="Return JSON with status.",
        user_prompt="test",
        json_mode=True,
        trace_id="trace-llm-test",
        venue_id="venue-test",
        agent_id="Router",
        agent_name="Router_Agent",
    )

    evidence = await db.fetch_one(
        "SELECT * FROM llm_call_logs WHERE trace_id = ? AND venue_id = ?",
        ("trace-llm-test", "venue-test"),
    )
    assert response.model_name == REQUIRED_GENERATIVE_MODEL
    assert response.is_mock is True
    assert evidence["status"] == "MOCKED"
    assert evidence["model_name"] == REQUIRED_GENERATIVE_MODEL
    assert bool(evidence["is_mock"]) is True
    assert evidence["request_id"] is None
    assert evidence["agent_id"] == "Router"
    assert evidence["agent_name"] == "Router_Agent"
    await db.close()

@pytest.mark.asyncio
async def test_watcher_direct_call_is_blocked_by_global_daily_quota(tmp_path, monkeypatch):
    import time

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.setenv("SCENIC_AGENT_DAILY_TOKEN_LIMIT", "1000")
    db = AsyncDBClient(tmp_path / "global-quota.db")
    await init_database(db)
    await db.execute(
        """
        INSERT INTO llm_call_logs (
            id, venue_id, trace_id, agent_id, agent_name, provider, model_name,
            status, attempt_count, latency_seconds, prompt_tokens,
            completion_tokens, total_tokens, request_id, is_mock, created_at
        ) VALUES (?, ?, ?, ?, ?, 'deepseek', ?, 'SUCCEEDED', 1, 1.0, ?, ?, ?, 'req', 0, ?)
        """,
        (
            "quota-used",
            "venue-global-quota",
            "a" * 32,
            "Watcher",
            "Watcher_Audit_Agent",
            REQUIRED_GENERATIVE_MODEL,
            1000,
            0,
            1000,
            time.time(),
        ),
    )
    client = LLMClient()
    client.set_database(db)

    async def must_not_call_provider():
        raise AssertionError("provider must not be called after quota exhaustion")

    monkeypatch.setattr(client, "get_client", must_not_call_provider)

    with pytest.raises(RuntimeError, match="QUOTA_EXCEEDED"):
        await client.ask(
            system_prompt="audit",
            user_prompt="batch",
            json_mode=True,
            trace_id="b" * 32,
            venue_id="venue-global-quota",
            agent_id="Watcher",
            agent_name="Watcher_Audit_Agent",
        )

    await db.close()
