from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def compose_config() -> dict:
    return yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))


def test_default_services_and_optional_profiles_are_explicit():
    services = compose_config()["services"]

    for name in ("app", "postgres", "redis", "nginx"):
        assert "profiles" not in services[name]

    # tei-embedding is co-resident: the app image is torch-free (ADR-0020), so the
    # embedding service must start with the default stack rather than behind a profile.
    assert "profiles" not in services["tei-embedding"]

    expected_profiles = {
        "tei-reranker": ["tei-reranker"],
        "tei-reranker-v2": ["rerank-v2"],
        "hatchet-postgres": ["agent-runtime"],
        "hatchet-migrate": ["agent-runtime"],
        "hatchet-admin": ["agent-runtime"],
        "hatchet-engine": ["agent-runtime"],
        "hatchet-api": ["agent-runtime"],
        "jaeger": ["tracing"],
    }
    for service, profiles in expected_profiles.items():
        assert services[service]["profiles"] == profiles


def test_tei_services_pin_image_models_and_memory_bounded_batches():
    services = compose_config()["services"]

    for name in ("tei-embedding", "tei-reranker", "tei-reranker-v2"):
        assert services[name]["image"] == "ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4"

    embedding_command = services["tei-embedding"]["command"]
    assert embedding_command[embedding_command.index("--model-id") + 1] == "BAAI/bge-m3"
    assert embedding_command[embedding_command.index("--max-batch-tokens") + 1] == "2048"

    reranker_command = services["tei-reranker"]["command"]
    assert reranker_command[reranker_command.index("--model-id") + 1] == "/data/bge-reranker-base-onnx"
    assert reranker_command[reranker_command.index("--max-batch-tokens") + 1] == "1024"

    v2_command = services["tei-reranker-v2"]["command"]
    assert v2_command[v2_command.index("--model-id") + 1] == "BAAI/bge-reranker-v2-m3"
    assert v2_command[v2_command.index("--max-batch-tokens") + 1] == "1024"


def test_hatchet_profile_is_split_and_migration_precedes_engine_and_api():
    services = compose_config()["services"]

    assert services["hatchet-migrate"]["depends_on"]["hatchet-postgres"]["condition"] == "service_healthy"
    assert services["hatchet-admin"]["depends_on"]["hatchet-migrate"]["condition"] == "service_completed_successfully"
    assert services["hatchet-engine"]["depends_on"]["hatchet-admin"]["condition"] == "service_completed_successfully"
    assert services["hatchet-api"]["depends_on"]["hatchet-admin"]["condition"] == "service_completed_successfully"
    assert "hatchet-lite" not in services

    engine_health = services["hatchet-engine"]["healthcheck"]["test"]
    api_health = services["hatchet-api"]["healthcheck"]["test"]
    assert any("/ready" in item for item in engine_health)
    assert any("/api/live" in item for item in api_health)


def test_jaeger_profile_exposes_otlp_and_has_healthcheck():
    service = compose_config()["services"]["jaeger"]

    assert service["image"] == "jaegertracing/all-in-one:1.62.0"
    assert service["environment"]["COLLECTOR_OTLP_ENABLED"] == "true"
    assert service["healthcheck"]["test"]
    published = {item.rsplit(":", 1)[-1] for item in service["ports"]}
    assert {"16686", "4317", "4318"} <= published


def test_nginx_exposes_readiness_probe_without_changing_liveness_healthcheck():
    nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    compose = compose_config()["services"]["nginx"]["healthcheck"]["test"]

    assert "location = /ready" in nginx
    assert compose[-1] == "http://127.0.0.1/health"
