"""Multi-model LLM fallback chain with CircuitBreaker integration."""
import os
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from openai import AsyncOpenAI

from src.memory_palace.tools.circuit_breaker import CircuitBreaker, CircuitOpenError
from src.memory_palace.tools.llm_wrapper import LLMResponse


@dataclass
class ModelConfig:
    name: str
    api_key: str
    base_url: str
    model: str


class LLMFallbackChain:
    """Try models in order. First success wins. Circuit-breakers gate each attempt."""

    def __init__(self, models: list[ModelConfig]):
        self.models = models
        self._clients: dict[str, AsyncOpenAI] = {}
        self._breakers: dict[str, CircuitBreaker] = {}

    def _client(self, cfg: ModelConfig) -> AsyncOpenAI:
        if cfg.name not in self._clients:
            self._clients[cfg.name] = AsyncOpenAI(
                api_key=cfg.api_key, base_url=cfg.base_url,
                timeout=float(os.environ.get("LLM_TIMEOUT", 30)),
                max_retries=0,
            )
        return self._clients[cfg.name]

    def _breaker(self, cfg: ModelConfig) -> CircuitBreaker:
        if cfg.name not in self._breakers:
            self._breakers[cfg.name] = CircuitBreaker(
                name=cfg.name, failure_threshold=3, recovery_timeout=30,
                success_threshold=1, timeout=30,
            )
        return self._breakers[cfg.name]

    async def call(self, messages: list, model: str, temperature: float,
                   max_tokens: Optional[int], json_mode: bool, trace_id: str) -> LLMResponse:
        """Try models in order. Return first success or raise when all exhausted."""
        import time

        last_error = None
        for cfg in self.models:
            breaker = self._breaker(cfg)
            client = self._client(cfg)
            try:
                kwargs = {
                    "model": cfg.model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                async def _call():
                    return await client.chat.completions.create(**kwargs)

                t0 = time.time()
                result = await breaker.call(_call)
                content = result.choices[0].message.content or ""
                tokens = result.usage.total_tokens if result.usage else 0
                return LLMResponse(
                    content=content, tokens_used=tokens,
                    model_name=cfg.model,
                    latency_seconds=time.time() - t0,
                )
            except CircuitOpenError:
                logger.warning(f"[Trace-{trace_id}] {cfg.name} circuit open, trying next")
                continue
            except Exception as e:
                logger.warning(f"[Trace-{trace_id}] {cfg.name} failed: {e}")
                last_error = e
                continue

        raise last_error or RuntimeError("All LLM models exhausted")


def build_fallback_chain() -> Optional[LLMFallbackChain]:
    """Build fallback chain from environment variables. Returns None if no fallback configured."""
    import os

    models = []

    # Primary: existing OPENAI_API_KEY (DeepSeek compatible)
    primary_key = os.environ.get("OPENAI_API_KEY", "")
    primary_url = os.environ.get("OPENAI_BASE_URL", "")
    primary_model = os.environ.get("LLM_DEFAULT_MODEL", "gpt-4o")
    if primary_key:
        models.append(ModelConfig("primary", primary_key, primary_url, primary_model))

    # Fallback: LLM_FALLBACK_* env vars
    fallback_key = os.environ.get("LLM_FALLBACK_API_KEY", "")
    fallback_url = os.environ.get("LLM_FALLBACK_BASE_URL", "")
    fallback_model = os.environ.get("LLM_FALLBACK_MODEL", "")
    if fallback_key:
        models.append(ModelConfig("fallback", fallback_key, fallback_url, fallback_model))

    if len(models) > 1:
        return LLMFallbackChain(models)
    return None
