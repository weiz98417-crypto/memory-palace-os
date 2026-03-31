"""
token_metrics.py - LLM Token 消耗指标收集器
"""
from prometheus_client import Counter, Histogram

TOKEN_BUCKETS = (100, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000)

# Token 消耗计数器
llm_tokens_total = Counter(
    "memory_palace_llm_tokens_total",
    "Total tokens consumed",
    ["provider", "model", "token_type"]
)

# 单次请求 Token 分布
llm_tokens_per_request = Histogram(
    "memory_palace_llm_tokens_per_request",
    "Tokens per LLM request",
    ["provider", "model", "token_type"],
    buckets=TOKEN_BUCKETS
)

# LLM 调用成本
llm_cost_total = Counter(
    "memory_palace_llm_cost_total",
    "Total LLM API cost in USD",
    ["provider", "model"]
)


class TokenMetricsCollector:
    """Token 消耗指标收集器"""

    # Token 单价（美元/1M tokens）
    TOKEN_PRICES = {
        "gpt-4o": {"input": 5.0, "output": 15.0},
        "gpt-4-turbo": {"input": 10.0, "output": 30.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        "default": {"input": 5.0, "output": 15.0},
    }

    @staticmethod
    def record_tokens(provider: str, model: str,
                     input_tokens: int = 0,
                     output_tokens: int = 0) -> None:
        """记录 Token 消耗"""
        if input_tokens > 0:
            llm_tokens_total.labels(provider=provider, model=model, token_type="input").inc(input_tokens)
            llm_tokens_per_request.labels(provider=provider, model=model, token_type="input").observe(input_tokens)

        if output_tokens > 0:
            llm_tokens_total.labels(provider=provider, model=model, token_type="output").inc(output_tokens)
            llm_tokens_per_request.labels(provider=provider, model=model, token_type="output").observe(output_tokens)

        # 计算成本
        prices = TokenMetricsCollector.TOKEN_PRICES.get(model, TokenMetricsCollector.TOKEN_PRICES["default"])
        cost = (input_tokens / 1_000_000) * prices["input"] + (output_tokens / 1_000_000) * prices["output"]
        if cost > 0:
            llm_cost_total.labels(provider=provider, model=model).inc(cost)


__all__ = ["TokenMetricsCollector"]
