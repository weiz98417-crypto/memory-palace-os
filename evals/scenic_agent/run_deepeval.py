from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evals.scenic_agent.contracts import (
    ContractViolation,
    GoldenFixtureError,
    MissingModelCredential,
    evaluate_contract,
    load_golden_cases,
    require_model_credential,
)


def _write_report(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def run_contract() -> dict[str, Any]:
    cases = load_golden_cases()
    for case in cases:
        evaluate_contract(case, case["calibration_observation"])
    return {
        "mode": "contract",
        "case_count": len(cases),
        "case_ids": [case["id"] for case in cases],
        "success": True,
    }


def _build_judge(api_key: str):
    from deepeval.models import OpenAIModel

    model_name = (
        os.environ.get("SCENIC_EVAL_MODEL")
        or os.environ.get("LLM_DEFAULT_MODEL")
        or "deepseek-flash"
    )
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
    return OpenAIModel(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        cost_per_input_token=0.0,
        cost_per_output_token=0.0,
    )


def _measure_grounded(case: dict[str, Any], judge) -> dict[str, Any]:
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    observation = case["calibration_observation"]
    test_case = LLMTestCase(
        input=case["query"],
        actual_output=observation["answer"],
        retrieval_context=[hit["excerpt"] for hit in case["knowledge_hits"]],
    )
    metric = FaithfulnessMetric(
        threshold=0.8,
        model=judge,
        async_mode=False,
        include_reason=True,
    )
    metric.measure(test_case)
    return {
        "metric": "Faithfulness",
        "score": metric.score,
        "threshold": metric.threshold,
        "success": metric.success,
        "reason": metric.reason,
    }


def _measure_no_evidence(case: dict[str, Any], judge) -> dict[str, Any]:
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    observation = case["calibration_observation"]
    test_case = LLMTestCase(input=case["query"], actual_output=observation["answer"])
    metric = GEval(
        name="No-evidence refusal",
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        # The product contract fixes the refusal wording to the four characters
        # ???? and forbids invention. The judge must not demand extra advice,
        # extra explanation, or a suggested human next step: that would penalise the
        # canonical minimal answer the contract requires.
        criteria=(
            "When no verified knowledge was retrieved, the answer must state that there "
            "is no basis (????) and must not invent a procedure, an SOP citation, or "
            "a fabricated source. A minimal canonical refusal is fully correct."
        ),
        evaluation_steps=[
            "Check the answer states there is no basis (????) or an exact equivalent.",
            "Check the answer does not invent an SOP, a historical case, or a source.",
            "Do not penalise the answer for being short, for omitting extra advice, or "
            "for not telling the user what a human should do next.",
        ],
        threshold=0.8,
        model=judge,
    )
    metric.measure(test_case)
    return {
        "metric": "GEval-NoEvidenceRefusal",
        "score": metric.score,
        "threshold": metric.threshold,
        "success": metric.success,
        "reason": metric.reason,
    }


def run_deepeval(report_path: str | None = None) -> dict[str, Any]:
    api_key = require_model_credential()
    judge = _build_judge(api_key)
    cases = load_golden_cases()
    results: list[dict[str, Any]] = []
    all_success = True

    for case in cases:
        evaluate_contract(case, case["calibration_observation"])
        if case["expected"]["evidence_status"] == "GROUNDED":
            metric_result = _measure_grounded(case, judge)
        else:
            metric_result = _measure_no_evidence(case, judge)
        all_success = all_success and bool(metric_result["success"])
        results.append(
            {
                "case_id": case["id"],
                "scenario_type": case["scenario_type"],
                "candidate_kind": case["calibration_observation"]["candidate_kind"],
                **metric_result,
            }
        )

    report = {
        "mode": "deepeval",
        "candidate_source": "CALIBRATION_FIXTURE",
        "candidate_not_model_output": True,
        "judge_model": os.environ.get("SCENIC_EVAL_MODEL")
        or os.environ.get("LLM_DEFAULT_MODEL")
        or "deepseek-flash",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "success": all_success,
    }
    _write_report(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run scenic agent golden-sample gates.")
    parser.add_argument(
        "--mode", choices=("contract", "deepeval", "live"), required=True
    )
    parser.add_argument("--report", help="Optional JSON report path.")
    args = parser.parse_args(argv)

    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    try:
        if args.mode == "contract":
            report = run_contract()
        elif args.mode == "live":
            from evals.scenic_agent.live_gate import run_live

            report = run_live(args.report)
        else:
            report = run_deepeval(args.report)
    except MissingModelCredential as exc:
        print(f"LIVE_EVAL_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (GoldenFixtureError, ContractViolation) as exc:
        print(f"EVAL_CONTRACT_FAILED: {exc}", file=sys.stderr)
        return 1

    if args.mode in {"contract", "live"}:
        _write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())



