"""Draw a deterministic, stratified sample from the corpus eval set."""

from __future__ import annotations

import argparse
import json
import pathlib


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="evals/scenic_agent/corpus_cases.json")
    parser.add_argument("--out", default="evals/scenic_agent/sample_100_cases.json")
    parser.add_argument("--size", type=int, default=100)
    args = parser.parse_args()

    payload = json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    cases = payload["cases"]

    grounded = [c for c in cases if c["expected"]["evidence_status"] == "GROUNDED"]
    no_evidence = [c for c in cases if c["expected"]["evidence_status"] == "NO_EVIDENCE"]
    hard = [c for c in grounded if c.get("evaluation_origin") == "SYNTHETIC_HARD_PHRASING"]
    plain = [c for c in grounded if c.get("evaluation_origin") == "SYNTHETIC_FROM_CORPUS"]

    # Keep every no-evidence case (they are the refusal gate) and fill the rest from
    # the grounded buckets, spreading across sources instead of taking the first N.
    target = args.size
    picked: list[dict] = list(no_evidence)

    def spread(source_list: list[dict], wanted: int) -> list[dict]:
        """Round-robin over distinct source ids so the sample covers the whole corpus."""
        buckets: dict[str, list[dict]] = {}
        order: list[str] = []
        for case in source_list:
            key = case["knowledge_hits"][0]["source_id"]
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(case)
        result: list[dict] = []
        index = 0
        while len(result) < wanted and any(buckets.values()):
            for key in order:
                if len(result) >= wanted:
                    break
                if buckets[key]:
                    result.append(buckets[key].pop(0))
            index += 1
            if index > 10000:
                break
        return result

    remaining = target - len(picked)
    hard_target = min(len(hard), max(1, remaining // 4))
    picked.extend(spread(hard, hard_target))
    remaining = target - len(picked)
    picked.extend(spread(plain, remaining))

    sample = {
        "schema_version": 1,
        "fixture_only": False,
        "evaluation_origin": "STRATIFIED_SAMPLE_FROM_CORPUS",
        "source_corpus_size": len(cases),
        "cases": picked[:target],
    }
    pathlib.Path(args.out).write_text(
        json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    grounded_n = sum(1 for c in sample["cases"] if c["expected"]["evidence_status"] == "GROUNDED")
    print("sample:", len(sample["cases"]), "-> ", args.out)
    print("  grounded:", grounded_n, "| no-evidence:", len(sample["cases"]) - grounded_n)
    print("  distinct grounded sources:", len({c["knowledge_hits"][0]["source_id"] for c in sample["cases"] if c["knowledge_hits"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
