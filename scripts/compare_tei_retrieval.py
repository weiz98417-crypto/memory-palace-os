"""Compare retrieval before and after the TEI re-embed, using the real index."""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, "/app")

from src.memory_palace.knowledge.vector_store import PalaceVectorStore
from src.memory_palace.tools.embedding_client import TEIEmbeddingBackend

QUERIES = [
    "??????????????",
    "??????????????????",
    "???????????",
    "??????????",
    "??????????????",
    "????????????????",
    "????????????",
    "??????????????",
    "????????????",
    "?????????????",
]


def main() -> int:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/retrieval.json")
    backend = TEIEmbeddingBackend(
        base_url=os.environ.get("SCENIC_TEI_EMBEDDING_URL", "http://tei-embedding:80"),
        timeout=300,
        batch_size=4,
    )
    store = PalaceVectorStore(embedding_function=backend)
    venue = os.environ.get("DEFAULT_VENUE_ID", "venue-hq")
    report = []
    for query in QUERIES:
        hits = store.query_experience(
            query, top_k=5, threshold=0.0, venue_id=venue,
            source_types=["SOP"], strict=True,
        )
        report.append(
            {
                "query": query,
                "ids": [str(hit.get("id")) for hit in hits],
                "scores": [round(float(hit.get("score") or 0), 8) for hit in hits],
            }
        )
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out, "queries:", len(report))
    for item in report:
        print(" ", item["ids"][0] if item["ids"] else "<none>", item["scores"][0] if item["scores"] else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
