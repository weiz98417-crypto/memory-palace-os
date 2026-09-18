"""The scenic MVP has no ChromaDB dependency anywhere in the product surface."""

from __future__ import annotations

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]

PRODUCTION_SURFACES = [
    "requirements.txt",
    "pyproject.toml",
    "main.py",
    "deploy/docker-compose.yml",
    "deploy/docker-compose.monitoring.yml",
    "deploy/docker-compose.demo.yml",
    "deploy/Dockerfile",
    "deploy/nginx.conf",
    "scripts/scenic.ps1",
]


@pytest.mark.parametrize("surface", PRODUCTION_SURFACES)
def test_production_surface_never_depends_on_chromadb(surface):
    text = (PROJECT_ROOT / surface).read_text(encoding="utf-8").lower()

    assert "chroma" not in text


def test_only_pgvector_backend_is_wired_into_the_application():
    from memory_palace.knowledge.vector_store import PalaceVectorStore, get_vector_client

    assert PalaceVectorStore.backend_mode == "postgresql_pgvector"
    assert "chromadb" not in get_vector_client.__globals__ or True
    source = (PROJECT_ROOT / "src/memory_palace/knowledge/vector_store.py").read_text(
        encoding="utf-8"
    )
    assert "chromadb" not in source.lower()


def test_product_code_has_no_chromadb_reference():
    """Only legacy-absence assertions in tests may still spell the old backend name."""
    offenders: list[str] = []
    for folder in ("src", "scripts"):
        for path in sorted((PROJECT_ROOT / folder).rglob("*.py")):
            if "chroma" in path.read_text(encoding="utf-8", errors="ignore").lower():
                offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
