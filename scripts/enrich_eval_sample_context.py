"""Enrich the eval sample with the index's real top-5 context per query."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, "/app")

from src.memory_palace.knowledge.vector_store import PalaceVectorStore
from src.memory_palace.tools.embedding_client import TEIEmbeddingBackend


def _hit(source_id: str, metadata: dict, title: str) -> dict:
    return {
        "source_id": str(source_id),
        "source_type": "SOP",
        "title": str(title),
        "version": str(metadata.get("version") or "1.0"),
        "excerpt": str(metadata.get("excerpt") or metadata.get("content") or title)[:400],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", default="/app/evals/scenic_agent/sample_100_cases.json")
    parser.add_argument("--out", default="/app/evals/scenic_agent/sample_100_cases.json")
    # Production scenic retrieval uses 0.55; grounded queries score 0.69-0.82 and
    # out-of-corpus queries score 0.37-0.43, so 0.55 is the separation point.
    parser.add_argument("--threshold", type=float, default=0.55)
    args = parser.parse_args()

    backend = TEIEmbeddingBackend(
        base_url=os.environ.get("SCENIC_TEI_EMBEDDING_URL", "http://tei-embedding:80"),
        timeout=300,
        batch_size=8,
    )
    store = PalaceVectorStore(embedding_function=backend)
    payload = json.loads(pathlib.Path(args.sample).read_text(encoding="utf-8"))

    enriched = 0
    for case in payload["cases"]:
        venue = case["incident_context"]["venue_id"]
        hits = store.query_experience(
            case["query"], top_k=5, threshold=args.threshold, venue_id=venue,
            source_types=["SOP"], strict=True,
        )
        context: list[dict] = []
        seen: set[str] = set()
        for hit in hits:
            metadata = hit.get("metadata") or {}
            source_id = str(metadata.get("source_id") or hit.get("id"))
            if source_id in seen:
                continue
            seen.add(source_id)
            title = str(metadata.get("title") or metadata.get("knowledge_title") or "")
            context.append(_hit(source_id, metadata, title))
        # The context is exactly what the index returns at the production threshold.
        # Nothing is padded in: an out-of-corpus query must reach the trunk with an empty
        # context so the refusal path is exercised honestly.
        case["retrieved_context"] = context
        case["knowledge_hits"] = context
        enriched += 1
    payload["context_source"] = "LIVE_TOP5_FROM_INDEX"
    pathlib.Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    sizes = [len(c["knowledge_hits"]) for c in payload["cases"]]
    print("enriched:", enriched, "| avg context size:", round(sum(sizes) / max(1, len(sizes)), 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
