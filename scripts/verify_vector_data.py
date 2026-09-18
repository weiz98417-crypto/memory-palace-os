"""Verify that pgvector holds the data the formal business chain requires.

This is a read-only check. It fails with a non-zero exit code when required data is
missing, so it can be used in startup checks and in evidence collection.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

INDEX_NAME = "knowledge_vectors_bge_m3_v1"
DIMENSION = 1024
REQUIRED_SOURCE_TYPES = ("SOP",)


def _connect(dsn: str):
    import psycopg

    return psycopg.connect(dsn)


def collect_evidence(dsn: str) -> dict[str, Any]:
    with _connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT index_name, model_name, model_version, dimension, status
            FROM vector_index_versions
            WHERE index_name = %s
            """,
            (INDEX_NAME,),
        )
        version_row = cursor.fetchone()
        if version_row is None:
            raise SystemExit(f"pgvector index version is missing: {INDEX_NAME}")
        index = {
            "index_name": version_row[0],
            "model_name": version_row[1],
            "model_version": version_row[2],
            "dimension": int(version_row[3]),
            "status": version_row[4],
        }
        if index["dimension"] != DIMENSION or index["status"] != "READY":
            raise SystemExit(f"pgvector index contract is not ready: {index}")

        cursor.execute(
            """
            SELECT venue_id, source_type, COUNT(*)
            FROM knowledge_vectors
            WHERE index_name = %s
            GROUP BY venue_id, source_type
            ORDER BY venue_id, source_type
            """,
            (INDEX_NAME,),
        )
        counts: dict[str, dict[str, int]] = {}
        for venue_id, source_type, total in cursor.fetchall():
            counts.setdefault(str(venue_id), {})[str(source_type)] = int(total)

        cursor.execute(
            """
            SELECT COUNT(*) FROM knowledge_vectors
            WHERE index_name = %s AND (dimension <> %s OR index_status <> 'READY')
            """,
            (INDEX_NAME, DIMENSION),
        )
        unhealthy_vectors = int(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT sop.venue_id, sop.id, sop.title
            FROM sop_documents AS sop
            WHERE sop.status = 'PUBLISHED'
              AND NOT EXISTS (
                SELECT 1 FROM knowledge_vectors AS vector
                WHERE vector.venue_id = sop.venue_id
                  AND vector.index_name = %s
                  AND vector.source_type = 'SOP'
                  AND vector.source_id = sop.id::text
              )
            ORDER BY sop.venue_id, sop.id
            """,
            (INDEX_NAME,),
        )
        missing_sops = [
            {"venue_id": str(row[0]), "sop_id": str(row[1]), "title": str(row[2])}
            for row in cursor.fetchall()
        ]

    return {
        "index": index,
        "counts_by_venue_and_source_type": counts,
        "unhealthy_vector_count": unhealthy_vectors,
        "published_sops_without_vector": missing_sops,
    }


def evaluate(evidence: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if evidence["unhealthy_vector_count"]:
        problems.append(
            f"{evidence['unhealthy_vector_count']} vectors are not READY/{DIMENSION}-dimensional"
        )
    if evidence["published_sops_without_vector"]:
        problems.append(
            f"{len(evidence['published_sops_without_vector'])} published SOP documents have no vector"
        )
    for venue_id, counts in evidence["counts_by_venue_and_source_type"].items():
        for source_type in REQUIRED_SOURCE_TYPES:
            if counts.get(source_type, 0) < 1:
                problems.append(f"venue {venue_id} has no {source_type} vector")
    if not evidence["counts_by_venue_and_source_type"]:
        problems.append("pgvector holds no vectors for any venue")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the evidence document")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required")

    evidence = collect_evidence(dsn)
    problems = evaluate(evidence)

    if args.json:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    else:
        print(
            "pgvector index {index_name} ({dimension}d, {status}), "
            "model {model_name} / {model_version}".format(**evidence["index"])
        )
        for venue_id, counts in sorted(evidence["counts_by_venue_and_source_type"].items()):
            summary = ", ".join(f"{name}={total}" for name, total in sorted(counts.items()))
            print(f"  {venue_id}: {summary}")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print("pgvector data contract satisfied")


if __name__ == "__main__":
    main()
