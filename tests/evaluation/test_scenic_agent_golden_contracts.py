from copy import deepcopy

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
