"""Guard the ticket-11 docs/config sync for the scenic Agent trunk.

These tests encode the acceptance criteria: the retired ChromaDB / 1536-dimension vector
contract and the older four-layer agent runtime description must not reappear in active
documentation, configuration, or product pages. Historical ADRs and explicitly superseded
snapshots are exempt by design.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Historical snapshots that carry an explicit "Status: superseded" banner.
SUPERSEDED_ROOT_MARKERS = {
    "docs/verification/enterprise-demo-v1",
    "docs/verification/mvp-uat-20260728",
    "docs/product",
}

ACTIVE_DOC_PATHS = [
    "README.md",
    "CONTEXT.md",
    "docs/architecture.md",
    "docs/api_reference.md",
    "docs/vector-data-contract.md",
    "docs/operations/mvp-windows-docker.md",
    "docs/operations/mvp-backup-restore.md",
    "docs/enterprise-demo/README.md",
    "docs/enterprise-demo/architecture.md",
    "docs/enterprise-demo/variables.md",
    "docs/enterprise-demo/tests.md",
    "docs/enterprise-demo/failure-playbook.md",
    "static/product/index.template.html",
    "static/product/index.html",
]

ACTIVE_CONFIG_PATHS = [
    ".env.example",
    "deploy/docker-compose.yml",
    "deploy/docker-compose.demo.yml",
]

RETIRED_PATTERNS = [
    re.compile(r"\bchroma(db)?\b", re.IGNORECASE),
    re.compile(r"\b1536\b"),
]

AGENT_TRUNK_TERMS = ["IncidentCommand", "Hatchet", "pydantic-ai", "LiteLLM"]

MODEL_SERVICE_TERM = "\u6a21\u578b\u670d\u52a1"


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def _active_paths() -> list[str]:
    paths: list[str] = []
    for relative in ACTIVE_DOC_PATHS + ACTIVE_CONFIG_PATHS:
        if (PROJECT_ROOT / relative).is_file():
            paths.append(relative)
    for path in sorted((PROJECT_ROOT / "docs" / "architecture").glob("*.md")):
        paths.append(str(path.relative_to(PROJECT_ROOT)))
    return paths


def test_active_docs_and_config_have_no_retired_vector_contract():
    offenders: list[str] = []
    for relative in _active_paths():
        text = _read(relative)
        for pattern in RETIRED_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{relative}: {pattern.pattern}")
    assert offenders == []


def test_active_docs_and_config_use_the_current_generative_model_name():
    offenders = [
        relative
        for relative in _active_paths()
        if "deepseek-v4-flash" in _read(relative)
    ]
    assert offenders == []


def test_product_page_states_the_agent_trunk_terms():
    text = _read("static/product/index.template.html")
    missing = [term for term in AGENT_TRUNK_TERMS if term not in text]
    assert missing == []


def test_readme_states_the_agent_trunk_stack():
    text = _read("README.md")
    for term in AGENT_TRUNK_TERMS + ["DeepEval", "Jaeger", "TEI"]:
        assert term in text, term


def test_model_service_term_is_referenced_by_code_or_spec():
    assert MODEL_SERVICE_TERM in _read("CONTEXT.md")

    reference_surfaces = [
        "src/memory_palace/operations/runtime_diagnostics.py",
        "docs/architecture/scenic-agent-diagnostics-observability.md",
        "docs/architecture.md",
    ]
    assert any(
        MODEL_SERVICE_TERM in _read(relative) for relative in reference_surfaces
    )


def test_historical_snapshots_declare_superseded_status():
    for relative_root in SUPERSEDED_ROOT_MARKERS:
        root = PROJECT_ROOT / relative_root
        if not root.is_dir():
            continue
        texts = [
            path.read_text(encoding="utf-8", errors="ignore")
            for path in root.rglob("*.md")
        ]
        assert any("superseded" in text.lower() for text in texts), relative_root
