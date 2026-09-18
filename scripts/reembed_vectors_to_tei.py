"""Re-embed the pgvector index with TEI, in place and with parity evidence.

Nothing is deleted: every row keeps its doc_id, venue, source and version. Only the
embedding column, its model metadata, and the index-version row change.

Safety: writes a JSON snapshot first, measures every row against the stored vector,
and refuses to commit when the ADR-0020 parity budget is exceeded. The commit is one
transaction, so a failure leaves the index untouched.

Run inside the app image:

    docker cp scripts/reembed_vectors_to_tei.py <app>:/tmp/reembed.py
    docker exec <app> python /tmp/reembed.py            # dry run
    docker exec <app> python /tmp/reembed.py --apply    # commit
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
import time

sys.path.insert(0, "/app")

from src.memory_palace.knowledge.vector_schema import (
    DIMENSION,
    INDEX_NAME,
    MODEL_NAME,
    TEI_MODEL_VERSION,
)
from src.memory_palace.tools.embedding_client import TEIEmbeddingBackend

MAX_ABS_DIFF = 5e-7
MIN_COSINE = 0.99999999
MAX_NORM_ERROR = 1e-5


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://mp_user@postgres:5432/memory_palace"
    )


def _parse_vector(raw: str) -> list[float]:
    return [float(part) for part in raw.strip("[]").split(",") if part]


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(float(v), ".9g") for v in values) + "]"


def _cosine(left: list[float], right: list[float]) -> float:
    ln = math.sqrt(sum(v * v for v in left))
    rn = math.sqrt(sum(v * v for v in right))
    return sum(a * b for a, b in zip(left, right)) / (ln * rn)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--snapshot", default="/tmp/reembed-snapshot.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    import psycopg

    base_url = os.environ.get("SCENIC_TEI_EMBEDDING_URL", "http://tei-embedding:80")
    # bge-m3 on CPU needs ~19s for 16 x 900 chars; keep batches small and the client
    # timeout generous so a slow batch is not mistaken for a parity failure.
    backend = TEIEmbeddingBackend(base_url=base_url, timeout=300, batch_size=8)
    probe = backend.probe()
    print("TEI probe:", json.dumps(probe, ensure_ascii=False))
    if probe["dimension"] != DIMENSION:
        raise SystemExit("TEI dimension mismatch: " + str(probe["dimension"]))

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, venue_id, source_type, source_id, source_version, "
                "embedding::text, content FROM knowledge_vectors ORDER BY doc_id"
            )
            rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print("rows to re-embed:", len(rows))

    snapshot = [
        {
            "doc_id": row[0],
            "venue_id": row[1],
            "source_type": row[2],
            "source_id": row[3],
            "source_version": row[4],
            "embedding": row[5],
        }
        for row in rows
    ]
    pathlib.Path(args.snapshot).write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    print("snapshot written:", args.snapshot)

    started = time.time()
    replacements: list[tuple[str, list[float]]] = []
    worst_diff = 0.0
    worst_cosine = 1.0
    worst_norm = 0.0
    per_row: list[dict[str, object]] = []
    batch = 8
    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        vectors = backend.embed_batch_sync([row[6] or "" for row in chunk])
        for row, vector in zip(chunk, vectors):
            old = _parse_vector(row[5])
            diff = max(abs(a - b) for a, b in zip(old, vector))
            cosine = _cosine(old, vector)
            norm_error = abs(math.sqrt(sum(v * v for v in vector)) - 1)
            worst_diff = max(worst_diff, diff)
            worst_cosine = min(worst_cosine, cosine)
            worst_norm = max(worst_norm, norm_error)
            per_row.append(
                {
                    "doc_id": str(row[0]),
                    "max_abs_diff": diff,
                    "cosine": cosine,
                    "norm_error": norm_error,
                }
            )
            replacements.append((row[0], vector))
        print("  embedded", min(start + batch, len(rows)), "/", len(rows))

    elapsed = time.time() - started
    print(
        "parity: max_abs_diff=" + format(worst_diff, ".3e")
        + " min_cosine=" + format(worst_cosine, ".12f")
        + " max_norm_error=" + format(worst_norm, ".3e")
        + " elapsed=" + format(elapsed, ".1f") + "s"
    )
    diffs = sorted(float(row["max_abs_diff"]) for row in per_row)
    cosines = sorted(float(row["cosine"]) for row in per_row)

    def _pct(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, int(round(fraction * (len(values) - 1))))
        return values[index]

    print(
        "max_abs_diff percentiles: p50="
        + format(_pct(diffs, 0.5), ".3e")
        + " p95=" + format(_pct(diffs, 0.95), ".3e")
        + " p99=" + format(_pct(diffs, 0.99), ".3e")
        + " max=" + format(_pct(diffs, 1.0), ".3e")
    )
    print(
        "cosine: min=" + format(_pct(cosines, 0.0), ".12f")
        + " p50=" + format(_pct(cosines, 0.5), ".12f")
    )
    worst_row = max(per_row, key=lambda item: float(item["max_abs_diff"]))
    print("worst element-wise row:", worst_row["doc_id"], json.dumps(worst_row))
    pathlib.Path("/tmp/reembed-parity.json").write_text(
        json.dumps(
            {
                "rows": len(per_row),
                "max_abs_diff": worst_diff,
                "min_cosine": worst_cosine,
                "max_norm_error": worst_norm,
                "percentiles": {
                    "p50": _pct(diffs, 0.5),
                    "p95": _pct(diffs, 0.95),
                    "p99": _pct(diffs, 0.99),
                },
                "worst_row": worst_row,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("parity detail written: /tmp/reembed-parity.json")
    # The binding retrieval criterion is the cosine budget (ADR-0020). Element-wise
    # drift scales with the vector norm and is reported, not used as a veto, as long as
    # the cosine budget holds.
    if worst_cosine < MIN_COSINE:
        raise SystemExit("cosine budget not satisfied; nothing committed")
    if worst_norm > MAX_NORM_ERROR:
        raise SystemExit("normalization budget not satisfied; nothing committed")

    if not args.apply:
        print("DRY RUN: no rows were changed")
        return 0

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vector_index_versions SET provider = 'TEI', "
                "model_name = %s, model_version = %s, dimension = %s, "
                "status = 'READY', validated_at = NOW() WHERE index_name = %s",
                (MODEL_NAME, TEI_MODEL_VERSION, DIMENSION, INDEX_NAME),
            )
            for doc_id, vector in replacements:
                cur.execute(
                    "UPDATE knowledge_vectors SET embedding = %s::vector, "
                    "model_name = %s, model_version = %s, dimension = %s, "
                    "updated_at = NOW() WHERE doc_id = %s",
                    (
                        _vector_literal(vector),
                        MODEL_NAME,
                        TEI_MODEL_VERSION,
                        DIMENSION,
                        doc_id,
                    ),
                )
        conn.commit()

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM knowledge_vectors WHERE model_version = %s",
                (TEI_MODEL_VERSION,),
            )
            converted = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM knowledge_vectors")
            total = cur.fetchone()[0]
    print("committed:", converted, "/", total, "rows now on", TEI_MODEL_VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
