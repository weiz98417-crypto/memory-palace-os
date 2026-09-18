import pytest

from src.memory_palace.core.event_experience_candidates import (
    DeepSeekEventExperienceCandidateExtractor,
)
from src.memory_palace.tools.llm_wrapper import LLMClient, REQUIRED_GENERATIVE_MODEL
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database


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
