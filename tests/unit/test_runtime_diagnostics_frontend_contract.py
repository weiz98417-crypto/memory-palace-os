from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_diagnostics_page_renders_model_quota_circuit_and_optional_jaeger():
    source = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="jaeger-trace-link"' in source
    assert "modelRuntime=diagnostics.model_runtime" in source
    assert "tokenQuota=diagnostics.token_quota" in source
    assert "circuitBreaker=diagnostics.circuit_breaker" in source
    assert "observability=diagnostics.observability" in source
    assert "每日 Token 配额" in source
    assert "模型熔断器" in source
    assert "business_impact_on_unavailable" in source
