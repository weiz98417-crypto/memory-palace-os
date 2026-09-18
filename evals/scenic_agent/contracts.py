from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


GOLDEN_CASES_PATH = Path(__file__).with_name("golden_cases.json")
NO_BASIS_PHRASE = "没有依据"


class GoldenFixtureError(ValueError):
    """Raised when the checked-in golden fixtures do not satisfy their schema."""


class ContractViolation(AssertionError):
    """Raised when an observed advice result violates the fixture contract."""


class MissingModelCredential(RuntimeError):
    """Raised when a live judge run cannot find a real model credential."""


def _require_keys(value: Mapping[str, Any], keys: Sequence[str], location: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise GoldenFixtureError(f"{location} is missing required keys: {', '.join(missing)}")


def load_golden_cases(path: str | Path | None = None) -> list[dict[str, Any]]:
    fixture_path = Path(path) if path is not None else GOLDEN_CASES_PATH
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenFixtureError(f"cannot load golden cases from {fixture_path}: {exc}") from exc

    _require_keys(payload, ("schema_version", "fixture_only", "cases"), "golden fixture")
    if payload["schema_version"] != 1:
        raise GoldenFixtureError(f"unsupported golden fixture schema: {payload['schema_version']}")
    if payload["fixture_only"] is not True:
        raise GoldenFixtureError("golden cases must be explicitly marked fixture_only=true")
    if not isinstance(payload["cases"], list) or not payload["cases"]:
        raise GoldenFixtureError("golden fixture must contain at least one case")

    cases = payload["cases"]
    validate_golden_cases(cases)
    return cases


def validate_golden_cases(cases: Sequence[Mapping[str, Any]]) -> None:
    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        location = f"cases[{index}]"
        _require_keys(
            case,
            (
                "id",
                "scenario_type",
                "query",
                "retrieval_status",
                "knowledge_hits",
                "expected",
                "calibration_observation",
            ),
            location,
        )
        case_id = str(case["id"])
        if not case_id:
            raise GoldenFixtureError(f"{location}.id must not be empty")
        if case_id in seen_ids:
            raise GoldenFixtureError(f"duplicate golden case id: {case_id}")
        seen_ids.add(case_id)

        hits = case["knowledge_hits"]
        if not isinstance(hits, list):
            raise GoldenFixtureError(f"{location}.knowledge_hits must be a list")
        hit_ids = [str(hit.get("source_id") or "") for hit in hits]
        if any(not source_id for source_id in hit_ids):
            raise GoldenFixtureError(f"{location}.knowledge_hits contains a blank source_id")
        if len(hit_ids) != len(set(hit_ids)):
            raise GoldenFixtureError(f"{location}.knowledge_hits contains duplicate source_id values")

        expected = case["expected"]
        _require_keys(
            expected,
            (
                "evidence_status",
                "must_cite_source_ids",
                "required_substrings",
                "forbidden_substrings",
            ),
            f"{location}.expected",
        )
        expected_status = expected["evidence_status"]
        expected_citations = [str(source_id) for source_id in expected["must_cite_source_ids"]]
        unknown_expected_citations = sorted(set(expected_citations) - set(hit_ids))
        if unknown_expected_citations:
            raise GoldenFixtureError(
                f"{location}.expected cites sources absent from knowledge_hits: "
                f"{', '.join(unknown_expected_citations)}"
            )

        if hits:
            if case["retrieval_status"] != "HITS" or expected_status != "GROUNDED":
                raise GoldenFixtureError(f"{location} with hits must be HITS/GROUNDED")
            if not expected_citations:
                raise GoldenFixtureError(f"{location} grounded case must declare expected citations")
        else:
            if case["retrieval_status"] != "ZERO_HITS" or expected_status != "NO_EVIDENCE":
                raise GoldenFixtureError(f"{location} without hits must be ZERO_HITS/NO_EVIDENCE")
            if expected_citations:
                raise GoldenFixtureError(f"{location} no-evidence case cannot expect citations")
            if NO_BASIS_PHRASE not in expected["required_substrings"]:
                raise GoldenFixtureError(
                    f"{location} no-evidence case must require the exact phrase {NO_BASIS_PHRASE!r}"
                )

        observation = case["calibration_observation"]
        _require_keys(
            observation,
            ("evidence_status", "answer", "citations", "candidate_kind"),
            f"{location}.calibration_observation",
        )
        if observation["candidate_kind"] != "CALIBRATION_FIXTURE":
            raise GoldenFixtureError(
                f"{location}.calibration_observation must be marked CALIBRATION_FIXTURE"
            )
        evaluate_contract(case, observation)


def evaluate_contract(case: Mapping[str, Any], observation: Mapping[str, Any]) -> None:
    case_id = str(case.get("id") or "<unknown>")
    expected = case["expected"]
    expected_status = str(expected["evidence_status"])
    actual_status = str(observation.get("evidence_status") or "")
    if actual_status != expected_status:
        raise ContractViolation(
            f"{case_id}: expected evidence_status={expected_status}, got {actual_status!r}"
        )

    answer = str(observation.get("answer") or "")
    citations = [str(source_id) for source_id in observation.get("citations") or []]
    expected_citations = [str(source_id) for source_id in expected["must_cite_source_ids"]]
    allowed_citations = {str(hit["source_id"]) for hit in case["knowledge_hits"]}

    missing_citations = [source_id for source_id in expected_citations if source_id not in citations]
    if missing_citations:
        raise ContractViolation(
            f"{case_id}: answer is missing required citation(s): {', '.join(missing_citations)}"
        )

    unexpected_citations = sorted(set(citations) - allowed_citations)
    if unexpected_citations:
        raise ContractViolation(
            f"{case_id}: answer contains citation(s) not present in verified context: "
            f"{', '.join(unexpected_citations)}"
        )

    if expected_status == "NO_EVIDENCE":
        if citations:
            raise ContractViolation(f"{case_id}: no-evidence answer must not contain citations")
        if NO_BASIS_PHRASE not in answer:
            raise ContractViolation(
                f"{case_id}: no-evidence answer must explicitly contain {NO_BASIS_PHRASE!r}"
            )

    for required in expected.get("required_substrings") or []:
        if str(required) not in answer:
            raise ContractViolation(f"{case_id}: answer is missing required text {required!r}")
    for forbidden in expected.get("forbidden_substrings") or []:
        if str(forbidden) in answer:
            raise ContractViolation(f"{case_id}: answer contains forbidden text {forbidden!r}")


def require_model_credential(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    api_key = str(values.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        key_file = str(values.get("DEEPSEEK_API_KEY_FILE") or "").strip()
        if key_file:
            try:
                api_key = Path(key_file).read_text(encoding="utf-8-sig").strip()
            except OSError as exc:
                raise MissingModelCredential(
                    f"DEEPSEEK_API_KEY_FILE cannot be read: {key_file}"
                ) from exc
    if not api_key:
        raise MissingModelCredential(
            "DEEPSEEK_API_KEY is required for live DeepEval judge runs; "
            "missing credentials are a failure, not a skip"
        )
    return api_key

