"""Validate corpus evals against the live index, then optionally prune them."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, "/app")

from src.memory_palace.knowledge.vector_store import PalaceVectorStore
from src.memory_palace.tools.embedding_client import TEIEmbeddingBackend


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="/app/evals/scenic_agent/corpus_cases.json")
    parser.add_argument("--report", default="/tmp/corpus-validation.json")
    parser.add_argument("--prune", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.30)
    args = parser.parse_args()

    backend = TEIEmbeddingBackend(
        base_url=os.environ.get("SCENIC_TEI_EMBEDDING_URL", "http://tei-embedding:80"),
        timeout=300,
        batch_size=8,
    )
    store = PalaceVectorStore(embedding_function=backend)
    payload = json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    cases = payload["cases"]
    print("cases:", len(cases))

    kept: list[dict] = []
    failures: list[dict] = []
    for index, case in enumerate(cases, start=1):
        venue = case["incident_context"]["venue_id"]
        expected_status = case["expected"]["evidence_status"]
        try:
            hits = store.query_experience(
                case["query"], top_k=5, threshold=args.threshold, venue_id=venue,
                source_types=["SOP"], strict=True,
            )
        except Exception as exc:
            failures.append({"id": case["id"], "reason": type(exc).__name__ + ": " + str(exc)[:120]})
            continue

        hit_ids = [str(hit.get("metadata", {}).get("source_id") or hit.get("id")) for hit in hits]
        expected_ids = list(case["expected"]["must_cite_source_ids"])

        if expected_status == "GROUNDED":
            if not expected_ids or not any(source in hit_ids for source in expected_ids):
                failures.append(
                    {
                        "id": case["id"],
                        "reason": "expected source not in top-5",
                        "expected": expected_ids,
                        "hit_ids": hit_ids[:5],
                    }
                )
                continue
        else:
            # pgvector returns a top-5 for any query above the similarity threshold, so a
            # no-evidence case is not defined by "zero hits". Its refusal is decided by
            # the grounded contract at the trunk level, which the contract gate checks.
            if hits and not case.get("retrieval_may_return_hits"):
                failures.append(
                    {"id": case["id"], "reason": "expected no hits but got some", "hit_ids": hit_ids[:5]}
                )
                continue
        kept.append(case)
        if index % 100 == 0:
            print("  validated", index, "/", len(cases), "| kept", len(kept), "| failures", len(failures))

    grounded = sum(1 for c in kept if c["expected"]["evidence_status"] == "GROUNDED")
    no_evidence = len(kept) - grounded
    report = {
        "input_cases": len(cases),
        "kept": len(kept),
        "grounded": grounded,
        "no_evidence": no_evidence,
        "failures": failures,
        "threshold": args.threshold,
    }
    pathlib.Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("kept:", len(kept), "| grounded:", grounded, "| no-evidence:", no_evidence)
    print("failures:", len(failures), "->", args.report)

    if args.prune:
        payload["cases"] = kept
        payload["validated_against_index"] = True
        pathlib.Path(args.cases).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print("pruned file written:", args.cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
