"""Score the sampled trunk output with DeepEval (judge model + classic metrics)."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, "/app")


def _judge():
    from deepeval.models import OpenAIModel

    model_name = (
        os.environ.get("SCENIC_EVAL_MODEL")
        or os.environ.get("LLM_DEFAULT_MODEL")
        or "deepseek-flash"
    )
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        path = os.environ.get("DEEPSEEK_API_KEY_FILE", "")
        key = pathlib.Path(path).read_text(encoding="utf-8").strip() if path else ""
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY required for the judge; missing key is a failure")
    return OpenAIModel(
        model=model_name,
        api_key=key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1",
        temperature=0,
        cost_per_input_token=0.0,
        cost_per_output_token=0.0,
    )


def _faithfulness(case: dict, item: dict, judge) -> dict:
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(
        input=case["query"],
        actual_output=item["advice_text"] or "",
        retrieval_context=[h["excerpt"] for h in case["knowledge_hits"]],
    )
    metric = FaithfulnessMetric(threshold=0.8, model=judge, async_mode=False, include_reason=True)
    metric.measure(test_case)
    return {"metric": "Faithfulness", "score": metric.score, "threshold": metric.threshold, "success": metric.success, "reason": metric.reason}


def _refusal(case: dict, item: dict, judge) -> dict:
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    test_case = LLMTestCase(input=case["query"], actual_output=item["advice_text"] or "")
    metric = GEval(
        name="No-evidence refusal",
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        criteria=(
            "When no verified retrieval context exists, the answer must state that there "
            "is no basis (\u6ca1\u6709\u4f9d\u636e) and must not invent a procedure, an SOP "
            "citation, or a fabricated source. A minimal canonical refusal is fully correct."
        ),
        evaluation_steps=[
            "Check the answer states there is no basis.",
            "Check the answer does not invent an SOP, case, or source.",
            "Do not penalise the answer for being short or for omitting extra advice.",
        ],
        threshold=0.8,
        model=judge,
    )
    metric.measure(test_case)
    return {"metric": "GEval-NoEvidenceRefusal", "score": metric.score, "threshold": metric.threshold, "success": metric.success, "reason": metric.reason}


def _contextual_relevancy(case: dict, item: dict, judge) -> dict:
    from deepeval.metrics import ContextualRelevancyMetric
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(
        input=case["query"],
        actual_output=item["advice_text"] or "",
        retrieval_context=[h["excerpt"] for h in case["knowledge_hits"]],
    )
    metric = ContextualRelevancyMetric(threshold=0.7, model=judge, async_mode=False, include_reason=True)
    metric.measure(test_case)
    return {"metric": "ContextualRelevancy", "score": metric.score, "threshold": metric.threshold, "success": metric.success, "reason": metric.reason}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="/tmp/sample_100_final.json")
    parser.add_argument("--run", default="/tmp/sample-100.json")
    parser.add_argument("--report", default="/tmp/deepeval-report.json")
    parser.add_argument("--grounded-limit", type=int, default=20)
    args = parser.parse_args()

    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    cases = {c["id"]: c for c in json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))["cases"]}
    run = json.loads(pathlib.Path(args.run).read_text(encoding="utf-8"))
    items = [i for i in run["results"] if not i.get("error")]
    no_evidence = [i for i in items if i["expected_status"] == "NO_EVIDENCE"]
    grounded = [i for i in items if i["expected_status"] == "GROUNDED"][: args.grounded_limit]
    selected = no_evidence + grounded
    print("scoring:", len(selected), "cases (", len(no_evidence), "no-evidence +", len(grounded), "grounded )")

    judge = _judge()
    results = []
    started = time.time()
    for index, item in enumerate(selected, start=1):
        case = cases[item["case_id"]]
        entry = {"case_id": item["case_id"], "expected_status": item["expected_status"]}
        try:
            if item["expected_status"] == "GROUNDED":
                entry.update(_faithfulness(case, item, judge))
                entry["contextual"] = _contextual_relevancy(case, item, judge)
            else:
                entry.update(_refusal(case, item, judge))
        except Exception as exc:
            entry["error"] = type(exc).__name__ + ": " + str(exc)[:200]
            entry["success"] = False
        results.append(entry)
        print("  ", index, "/", len(selected), entry["case_id"], entry.get("score"), entry.get("success"))

    scored = [r for r in results if "score" in r]
    successes = [r for r in scored if r.get("success")]
    report = {
        "mode": "sample_deepeval",
        "judge_model": os.environ.get("SCENIC_EVAL_MODEL") or os.environ.get("LLM_DEFAULT_MODEL") or "deepseek-flash",
        "cases_scored": len(scored),
        "successes": len(successes),
        "success_rate": round(len(successes) / max(1, len(scored)), 4),
        "elapsed_seconds": round(time.time() - started, 1),
        "results": results,
    }
    pathlib.Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("success:", len(successes), "/", len(scored), "| elapsed:", report["elapsed_seconds"], "s")
    return 0 if scored and len(successes) == len(scored) else 1


if __name__ == "__main__":
    raise SystemExit(main())
