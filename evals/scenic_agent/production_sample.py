"""Production Sample adapter.

This file remains a production-distribution observation corpus. It is not relabeled as
Golden data and the adapter records missing Golden fields explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRODUCTION_SAMPLE_PATH = Path(__file__).with_name("sample_100_cases.json")


class ProductionSampleError(ValueError):
    pass


def adapt_production_sample_case(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected") or {}
    retrieval_status = str(case.get("retrieval_status") or "")
    evidence_status = str(expected.get("evidence_status") or "")
    missing_fields = [
        field
        for field in (
            "artifact",
            "expected_risk",
            "requires_human_approval",
            "required_tools",
            "expected_actions",
            "expected_model_calls",
            "allowed_degradations",
            "expected_sse_events",
            "failure_mode",
            "source",
        )
        if field not in case
    ]
    normalized_artifact = "ADVICE"
    normalized_retrieval = {
        "HITS": "HITS",
        "NO_HITS": "ZERO_HITS",
        "ZERO_HITS": "ZERO_HITS",
    }.get(retrieval_status, retrieval_status)
    normalized = {
        "id": f"production-{case.get('id') or 'unknown'}",
        "artifact": normalized_artifact,
        "query": str(case.get("query") or ""),
        "retrieval_status": normalized_retrieval,
        "evidence_status": evidence_status,
        "incident_context": dict(case.get("incident_context") or {}),
        "knowledge_hits": list(case.get("knowledge_hits") or []),
        "expected": {
            "evidence_status": evidence_status,
            "must_cite_source_ids": list(expected.get("must_cite_source_ids") or []),
            "required_substrings": list(expected.get("required_substrings") or []),
            "forbidden_substrings": list(expected.get("forbidden_substrings") or []),
        },
        "missing_fields": missing_fields,
        "candidate_pool": "PRODUCTION_SAMPLE",
        "not_golden": True,
    }
    return normalized


def load_production_sample(path: str | Path | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else PRODUCTION_SAMPLE_PATH
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionSampleError(f"cannot load production sample: {exc}") from exc
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 100:
        raise ProductionSampleError("production sample must contain exactly 100 cases")
    adapted = [adapt_production_sample_case(case) for case in cases]
    return {
        "source_file": fixture_path.name,
        "schema_version": payload.get("schema_version"),
        "fixture_only": bool(payload.get("fixture_only")),
        "evaluation_origin": payload.get("evaluation_origin"),
        "case_count": len(adapted),
        "cases": adapted,
    }


__all__ = [
    "PRODUCTION_SAMPLE_PATH",
    "ProductionSampleError",
    "adapt_production_sample_case",
    "load_production_sample",
]
