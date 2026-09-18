import pytest

from src.memory_palace.core.health import (
    CheckStatus,
    DependencyCheckResult,
    HTTPHealthChecker,
    RedisHealthChecker,
    build_readiness_response,
    aggregate_status,
    register_configured_http_checks,
)


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeClient:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url):
        self.calls.append(url)
        return FakeResponse(self.status_code)


class RegistrySpy:
    def __init__(self):
        self.checkers = {}

    def register(self, name, checker):
        self.checkers[name] = checker


@pytest.mark.asyncio
async def test_http_health_checker_distinguishes_required_and_optional_failures():
    required_client = FakeClient(503)
    required = HTTPHealthChecker(
        name="tei_embedding",
        url="http://tei-embedding:80/health",
        required=True,
        client_factory=lambda **_kwargs: required_client,
    )
    optional_client = FakeClient(503)
    optional = HTTPHealthChecker(
        name="tei_reranker",
        url="http://tei-reranker:80/health",
        required=False,
        client_factory=lambda **_kwargs: optional_client,
    )

    required_result = await required.check()
    optional_result = await optional.check()

    assert required_result.status == CheckStatus.FAIL
    assert optional_result.status == CheckStatus.WARN
    assert required_client.calls == ["http://tei-embedding:80/health"]
    assert optional_client.calls == ["http://tei-reranker:80/health"]
    assert aggregate_status([required_result]).value == "unhealthy"
    assert aggregate_status([optional_result]).value == "degraded"


@pytest.mark.asyncio
async def test_http_health_checker_skips_unconfigured_optional_endpoint_without_a_request():
    client = FakeClient(200)
    checker = HTTPHealthChecker(
        name="jaeger",
        url="",
        required=False,
        client_factory=lambda **_kwargs: client,
    )

    result = await checker.check()

    assert result.status == CheckStatus.SKIP
    assert client.calls == []


def test_configured_http_checks_mark_tei_embedding_required_and_others_optional():
    registry = RegistrySpy()
    register_configured_http_checks(
        registry,
        {
            "SCENIC_TEI_EMBEDDING_HEALTH_URL": "http://tei-embedding:80/health",
            "SCENIC_TEI_RERANKER_HEALTH_URL": "http://tei-reranker:80/health",
            "HATCHET_HEALTH_URL": "http://hatchet-api:8080/api/live",
            "JAEGER_HEALTH_URL": "http://jaeger:14269/",
        },
    )

    assert registry.checkers["tei_embedding"].required is True
    assert registry.checkers["tei_reranker"].required is False
    assert registry.checkers["hatchet"].required is False
    assert registry.checkers["jaeger"].required is False
    assert registry.checkers["hatchet"].url == "http://hatchet-api:8080/api/live"


class ReadinessRegistryStub:
    def __init__(self, *results):
        self.results = list(results)

    async def check_all(self):
        return self.results

    def get_uptime(self):
        return 12.5


@pytest.mark.asyncio
async def test_readiness_response_is_degraded_for_optional_failure_and_unhealthy_for_required_failure():
    warn_code, warn_payload = await build_readiness_response(
        ReadinessRegistryStub(DependencyCheckResult(name="tei_reranker", status=CheckStatus.WARN)),
        version="test-version",
    )
    fail_code, fail_payload = await build_readiness_response(
        ReadinessRegistryStub(DependencyCheckResult(name="tei_embedding", status=CheckStatus.FAIL)),
        version="test-version",
    )

    assert warn_code == 200
    assert warn_payload["status"] == "degraded"
    assert warn_payload["version"] == "test-version"
    assert fail_code == 503
    assert fail_payload["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_redis_health_checker_accepts_boolean_ping_result():
    async def ping():
        return True

    result = await RedisHealthChecker(ping).check()

    assert result.status == CheckStatus.PASS
