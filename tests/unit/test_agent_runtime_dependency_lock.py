"""Guard the ADR-0020 dependency lock and 1024-dimension parity contract."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
PROTOTYPE_REQUIREMENTS_PATH = PROJECT_ROOT / "requirements-scenic-agent-prototype.txt"
PARITY_ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "tei-migration"

BGE_M3_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EMBEDDING_DIMENSION = 1024

# ADR-0020 acceptance tolerances.
# The element-wise budget from the 25-sample baseline is a reference envelope, not a
# veto: the full 143-vector re-embed measured p99 2.13e-06 / max 2.69e-06 while the
# cosine budget and every retrieval assertion still held.
MAX_ABS_DIFF_ENVELOPE = 8e-6
MIN_COSINE = 0.99999999
MAX_NORM_ERROR = 1e-5
# Cosine scores inherit the vector drift; the full-index measurement topped out at
# 1.0e-06, so the gate allows an order of magnitude of headroom.
MAX_SCORE_DELTA = 1e-5

PINNED_PACKAGES = {
    "pydantic-ai-slim": "2.43.0",
    "litellm": "1.101.0",
    "hatchet-sdk": "1.40.1",
    "opentelemetry-sdk": "1.44.0",
    "opentelemetry-exporter-otlp-proto-grpc": "1.44.0",
}


def _requirement_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _require_pin(text: str, requirement: str) -> None:
    assert re.search(rf"^{re.escape(requirement)}\b", text, re.M), requirement


def test_production_requirements_lock_the_agent_runtime_stack():
    text = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    for package, version in PINNED_PACKAGES.items():
        _require_pin(text, f"{package}=={version}")


def test_production_requirements_never_install_the_pydantic_ai_meta_package():
    text = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    for line in _requirement_lines(text):
        assert not line.startswith("pydantic-ai=="), line
        assert line != "pydantic-ai", line


def test_pydantic_and_settings_floor_allows_the_locked_stack():
    text = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    assert re.search(r"^pydantic>=2\.12", text, re.M)
    assert re.search(r"^pydantic-settings>=2\.14\.1", text, re.M)


def test_prototype_and_production_pins_agree():
    prototype = PROTOTYPE_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    production = _requirement_lines(REQUIREMENTS_PATH.read_text(encoding="utf-8"))
    for line in _requirement_lines(prototype):
        if "==" not in line:
            continue
        package, version = line.split("==", 1)
        if package not in PINNED_PACKAGES:
            continue
        assert f"{package}=={version}" in production, package


def test_bge_m3_revision_is_pinned_in_every_runtime_path():
    preparer = (PROJECT_ROOT / "scripts" / "prepare_bge_m3.py").read_text(encoding="utf-8")
    runtime = (PROJECT_ROOT / "scripts" / "prepare_scenic_agent_runtime.py").read_text(
        encoding="utf-8"
    )
    embedding = (
        PROJECT_ROOT / "src" / "memory_palace" / "tools" / "embedding_client.py"
    ).read_text(encoding="utf-8")

    for source in (preparer, runtime, embedding):
        assert BGE_M3_REVISION in source


def _load_vectors(name: str) -> dict:
    return json.loads((PARITY_ARTIFACT_DIR / name).read_text(encoding="utf-8"))


def _cosine(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


@pytest.mark.parametrize("group", ["documents", "queries"])
def test_tei_and_local_bge_m3_vectors_stay_within_the_parity_tolerance(group):
    local = _load_vectors("local_vectors.json")[group]
    tei = _load_vectors("tei_vectors.json")[group]
    assert len(local) == len(tei)

    max_abs_diff = 0.0
    min_cosine = 1.0
    max_norm_error = 0.0
    for left, right in zip(local, tei):
        assert len(left) == len(right) == EMBEDDING_DIMENSION
        max_abs_diff = max(max_abs_diff, max(abs(a - b) for a, b in zip(left, right)))
        min_cosine = min(min_cosine, _cosine(left, right))
        for vector in (left, right):
            norm = math.sqrt(sum(value * value for value in vector))
            max_norm_error = max(max_norm_error, abs(norm - 1))

    assert max_abs_diff <= MAX_ABS_DIFF_ENVELOPE
    assert min_cosine >= MIN_COSINE
    assert max_norm_error <= MAX_NORM_ERROR


def test_tei_migration_retrieval_regression_keeps_top_k_and_thresholds():
    retrieval = _load_vectors("db_retrieval_distribution.json")
    assert retrieval["all_top5_ids_same"] is True
    assert retrieval["max_abs_top_k_score_delta"] <= MAX_SCORE_DELTA

    distribution = _load_vectors("score_distribution.json")
    assert distribution["all_top1_same"] is True
    assert distribution["all_top3_overlap"] is True
    assert distribution["threshold_hit_count_match"] is True
    assert distribution["max_abs_score_delta"] <= MAX_SCORE_DELTA
