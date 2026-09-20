import json
from copy import deepcopy
from pathlib import Path

import pytest

from evals.scenic_agent.contracts import (
    ContractViolation,
    MissingModelCredential,
    evaluate_contract,
    load_golden_cases,
    require_model_credential,
    validate_golden_cases,
)


def case_by_type(scenario_type: str) -> dict:
    return next(case for case in load_golden_cases() if case["scenario_type"] == scenario_type)


def test_golden_cases_cover_device_crowd_and_no_evidence_with_explicit_expectations():
    cases = load_golden_cases()

    validate_golden_cases(cases)
    assert {case["scenario_type"] for case in cases} == {
        "DEVICE_ANOMALY",
        "CROWD_ALERT",
        "NO_KNOWLEDGE_HIT",
    }

    device = case_by_type("DEVICE_ANOMALY")
    crowd = case_by_type("CROWD_ALERT")
    no_hit = case_by_type("NO_KNOWLEDGE_HIT")

    assert device["expected"]["evidence_status"] == "GROUNDED"
    assert device["expected"]["must_cite_source_ids"]
    assert crowd["expected"]["evidence_status"] == "GROUNDED"
    assert crowd["expected"]["must_cite_source_ids"]
    assert no_hit["expected"]["evidence_status"] == "NO_EVIDENCE"
    assert no_hit["expected"]["must_cite_source_ids"] == []
    assert "没有依据" in no_hit["expected"]["required_substrings"]


def test_calibration_observations_satisfy_the_deterministic_contract():
    for case in load_golden_cases():
        evaluate_contract(case, case["calibration_observation"])


def test_grounded_contract_rejects_an_answer_without_its_expected_citation():
    case = case_by_type("DEVICE_ANOMALY")
    observation = deepcopy(case["calibration_observation"])
    observation["citations"] = []

    with pytest.raises(ContractViolation, match="citation"):
        evaluate_contract(case, observation)


def test_no_evidence_contract_rejects_invented_citations_or_missing_refusal():
    case = case_by_type("NO_KNOWLEDGE_HIT")
    invented = deepcopy(case["calibration_observation"])
    invented["citations"] = ["FIXTURE-SOP-NOT-IN-CONTEXT"]

    with pytest.raises(ContractViolation, match="citation"):
        evaluate_contract(case, invented)

    missing_refusal = deepcopy(case["calibration_observation"])
    missing_refusal["answer"] = "请按人工经验继续处置。"

    with pytest.raises(ContractViolation, match="没有依据"):
        evaluate_contract(case, missing_refusal)


def test_live_judge_requires_a_real_credential_and_does_not_skip_to_mock(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY_FILE", raising=False)

    with pytest.raises(MissingModelCredential, match="DEEPSEEK_API_KEY"):
        require_model_credential({})


def test_live_eval_cli_returns_failure_instead_of_skipping_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY_FILE", raising=False)
    from evals.scenic_agent.run_deepeval import main

    assert main(["--mode", "deepeval"]) == 2
    assert "LIVE_EVAL_BLOCKED" in capsys.readouterr().err


def test_fast_golden_has_exact_30_case_category_distribution():
    from evals.scenic_agent.contracts import load_fast_golden_cases

    fast_cases = load_fast_golden_cases()

    assert len(fast_cases) == 30
    counts: dict[str, int] = {}
    for case in fast_cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {
        "GROUNDED_ADVICE": 8,
        "NO_EVIDENCE": 5,
        "RETRIEVAL_SHAPE": 4,
        "DISPATCH_DRAFT": 3,
        "CLOSURE_SUMMARY": 3,
        "HITL_GATES": 3,
        "DEGRADATION_FAILURE": 2,
        "SECURITY_TENANT": 2,
    }
    assert len({case["dataset_version"] for case in fast_cases}) == 1
    assert all(case["fixture_only"] is True for case in fast_cases)
    source_counts: dict[str, int] = {}
    for case in fast_cases:
        source_counts[case["source"]] = source_counts.get(case["source"], 0) + 1
    assert source_counts == {
        "production": 18,
        "adversarial": 5,
        "expert": 4,
        "failure_replay": 3,
    }


def test_fast_golden_schema_enforces_artifact_sources_and_gate_fields():
    from evals.scenic_agent.contracts import load_fast_golden_cases

    for case in load_fast_golden_cases():
        assert case["artifact"] in {"ADVICE", "DISPATCH_DRAFT", "CLOSURE_SUMMARY"}
        assert case["expected_outcome"] in {"READY", "FAILED", "DEGRADED"}
        assert case["source"] in {"production", "expert", "adversarial", "failure_replay"}
        assert case["failure_mode"]
        assert case["expected_model_calls"]
        assert case["expected_sse_events"]
        if case["artifact"] == "ADVICE":
            assert case["expected_risk"] in {"P0", "P1", "P2", "P3", "P4"}
        if case["artifact"] in {"DISPATCH_DRAFT", "CLOSURE_SUMMARY"}:
            assert isinstance(case["requires_human_approval"], bool)
        if case["evidence_status"] == "GROUNDED":
            assert case["must_cite_source_ids"]
            assert set(case["must_cite_source_ids"]) <= {
                hit["source_id"] for hit in case["knowledge_hits"]
            }
        if case["evidence_status"] == "NO_EVIDENCE":
            assert case["must_cite_source_ids"] == []
            assert "没有依据" in case["required_substrings"]
        if case["artifact"] == "DISPATCH_DRAFT":
            assert any(
                event in {"DISPATCH_DRAFT_READY", "DISPATCH_DRAFT_FAILED"}
                for event in case["expected_sse_events"]
            )
        if case["artifact"] == "CLOSURE_SUMMARY":
            assert any(
                event in {"CLOSURE_SUMMARY_READY", "CLOSURE_SUMMARY_FAILED"}
                for event in case["expected_sse_events"]
            )


def test_legacy_golden_cases_normalize_through_v2_adapter():
    from evals.scenic_agent.case_schema import adapt_legacy_case
    from evals.scenic_agent.contracts import load_golden_cases

    legacy = load_golden_cases()[0]
    normalized = adapt_legacy_case(legacy)

    assert normalized["id"] == legacy["id"]
    assert normalized["artifact"] == "ADVICE"
    assert normalized["dataset_version"] == "legacy-v1"
    assert normalized["source"] == "expert"
    assert normalized["expected_outcome"] == "READY"


def test_fast_golden_loader_rejects_missing_required_fields(tmp_path):
    from evals.scenic_agent.contracts import GoldenFixtureError, load_fast_golden_cases

    payload = json.loads(
        (Path(__file__).resolve().parents[2] / "evals" / "scenic_agent" / "golden_fast_cases.json").read_text(
            encoding="utf-8"
        )
    )
    del payload["cases"][0]["expected_sse_events"]
    broken = tmp_path / "broken-fast.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GoldenFixtureError, match="expected_sse_events"):
        load_fast_golden_cases(broken)


def test_contract_runner_report_includes_smoke_and_fast_golden_sets(tmp_path):
    from evals.scenic_agent.run_deepeval import main

    report_path = tmp_path / "contract-report.json"
    assert main(["--mode", "contract", "--report", str(report_path)]) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["success"] is True
    assert report["case_sets"]["fast_smoke"]["case_count"] == 3
    assert report["case_sets"]["fast_golden"]["case_count"] == 30
    assert report["case_sets"]["fast_golden"]["category_counts"]["GROUNDED_ADVICE"] == 8
    assert report["case_sets"]["fast_golden"]["dataset_version"]
    fast_record = report["case_sets"]["fast_golden"]["cases"][0]
    assert fast_record["metric"] == "fast_golden_contract"
    assert fast_record["status"] == "PASS"
    assert fast_record["source"]
    smoke_record = report["case_sets"]["fast_smoke"]["cases"][0]
    assert smoke_record["dataset_version"] == "legacy-v1"
    assert smoke_record["status"] == "PASS"


def test_fast_golden_evaluator_rejects_semantically_invalid_cases():
    from evals.scenic_agent.case_schema import evaluate_fast_golden_case
    from evals.scenic_agent.contracts import load_fast_golden_cases

    base = deepcopy(load_fast_golden_cases()[0])

    unknown_sse = deepcopy(base)
    unknown_sse["expected_sse_events"] = ["ADVICE_PENDING", "ADVICE_MAGIC"]
    with pytest.raises(ValueError, match="unsupported SSE"):
        evaluate_fast_golden_case(unknown_sse)

    unknown_action = deepcopy(base)
    unknown_action["expected_actions"] = ["DO_SOMETHING_UNKNOWN"]
    with pytest.raises(ValueError, match="unsupported expected action"):
        evaluate_fast_golden_case(unknown_action)

    contradictory_gate = deepcopy(base)
    contradictory_gate["category"] = "HITL_GATES"
    contradictory_gate["requires_human_approval"] = False
    with pytest.raises(ValueError, match="HITL_GATES"):
        evaluate_fast_golden_case(contradictory_gate)


def test_production_sample_adapter_keeps_observation_semantics_and_missing_fields():
    from evals.scenic_agent.production_sample import load_production_sample

    sample = load_production_sample()

    assert sample["source_file"] == "sample_100_cases.json"
    assert sample["case_count"] == 100
    assert len({case["id"] for case in sample["cases"]}) == 100
    first = sample["cases"][0]
    assert first["candidate_pool"] == "PRODUCTION_SAMPLE"
    assert first["not_golden"] is True
    assert "artifact" in first["missing_fields"]
    assert "expected_risk" in first["missing_fields"]


def test_production_sample_runner_reports_non_golden_mode(tmp_path):
    from evals.scenic_agent.run_deepeval import main

    report_path = tmp_path / "production-sample.json"
    assert main(["--mode", "production-sample", "--report", str(report_path)]) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "production-sample"
    assert report["case_count"] == 100
    assert report["not_golden"] is True


def test_deep_golden_has_exact_120_case_distribution():
    from evals.scenic_agent.contracts import load_deep_golden_cases

    cases = load_deep_golden_cases()
    assert len(cases) == 120
    counts: dict[str, int] = {}
    sources: dict[str, int] = {}
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
        sources[case["source"]] = sources.get(case["source"], 0) + 1
    assert counts == {
        "GROUNDED_ADVICE": 24,
        "NO_EVIDENCE": 16,
        "RETRIEVAL_SHAPE": 14,
        "ROUTER_RISK": 10,
        "DISPATCH_DRAFT": 14,
        "CLOSURE_SUMMARY": 12,
        "HITL_GATES": 10,
        "DEGRADATION_FAILURE": 8,
        "SECURITY_TENANT": 6,
        "MULTI_AGENT_TRAJECTORY": 6,
    }
    assert sources == {"production": 72, "adversarial": 18, "expert": 18, "failure_replay": 12}
    assert report_has_deep_golden()


def report_has_deep_golden() -> bool:
    from evals.scenic_agent.run_deepeval import run_contract

    report = run_contract()
    return report["case_sets"]["deep_golden"]["case_count"] == 120