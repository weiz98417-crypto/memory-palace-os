"""Corpus-tier trigger policy and loader."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable

CORPUS_CASES_PATH = Path(__file__).with_name("corpus_cases.json")
TRIGGER_PREFIXES = (
    "src/memory_palace/knowledge/",
    "src/memory_palace/tools/llm_wrapper.py",
    "evals/scenic_agent/corpus_cases.json",
    "requirements-scenic-agent",
)
TRIGGER_TERMS = ("model", "embedding", "rerank", "retrieval", "chunk", "index")


class CorpusGateError(ValueError):
    pass


def should_run_corpus(changed_paths: Iterable[str]) -> bool:
    paths = [str(path).replace("\\", "/").lower() for path in changed_paths]
    return any(
        path.startswith(prefix.lower()) or any(term in path for term in TRIGGER_TERMS)
        for path in paths
        for prefix in TRIGGER_PREFIXES
    )


def load_corpus_cases(path: str | Path | None = None) -> dict:
    fixture_path = Path(path) if path else CORPUS_CASES_PATH
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusGateError(f"cannot load corpus cases: {exc}") from exc
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 860:
        raise CorpusGateError("corpus must contain exactly 860 cases")
    return payload


__all__ = ["CORPUS_CASES_PATH", "CorpusGateError", "load_corpus_cases", "should_run_corpus"]
