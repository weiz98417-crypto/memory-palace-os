import pytest

from src.memory_palace.scenic.advice_runtime import AdviceRuntimeConfig


def test_advice_runtime_defaults_to_redis_even_with_residual_hatchet_token(monkeypatch):
    monkeypatch.delenv("ADVICE_EXECUTION_MODE", raising=False)
    monkeypatch.setenv("HATCHET_CLIENT_TOKEN_FILE", "/tokens/worker")

    config = AdviceRuntimeConfig.from_env()

    assert config.mode == "redis"


def test_hatchet_mode_requires_a_readable_nonempty_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ADVICE_EXECUTION_MODE", "hatchet")
    token_file = tmp_path / "worker"
    token_file.write_text("\n", encoding="utf-8")
    monkeypatch.delenv("HATCHET_CLIENT_TOKEN", raising=False)
    monkeypatch.setenv("HATCHET_CLIENT_TOKEN_FILE", str(token_file))

    with pytest.raises(RuntimeError, match="Hatchet token"):
        AdviceRuntimeConfig.from_env()


def test_unknown_advice_runtime_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("ADVICE_EXECUTION_MODE", "automatic")

    with pytest.raises(RuntimeError, match="ADVICE_EXECUTION_MODE"):
        AdviceRuntimeConfig.from_env()
