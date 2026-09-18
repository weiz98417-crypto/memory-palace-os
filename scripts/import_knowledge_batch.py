"""Bulk-import collected source material as knowledge entries (source_type=IMPORT).

Uses the formal ``POST /api/v1/admin/knowledge/import`` endpoint, which writes the
knowledge rows and their pgvector entries in one transaction per batch.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _entry(query: str, result: dict) -> dict:
    title = (result.get("title") or "未命名来源").strip()[:200]
    body = (result.get("content") or result.get("snippet") or "").strip()
    url = result.get("url") or ""
    content = f"{body}\n\n来源：{url}\n检索主题：{query}"
    return {
        "title": title,
        "content": content[:19000],
        "category": "公开来源检索",
        "source_type": "IMPORT",
        "source_id": url[:128] if url else None,
        "tags": ["anysearch", *[part for part in query.split() if part][:6]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=PROJECT_ROOT / "artifacts" / "knowledge" / "anysearch-raw.json")
    parser.add_argument("--base-url", default=os.environ.get("SCENIC_DEMO_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--username", default="wangfang")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "artifacts" / "knowledge" / "knowledge-import-report.json")
    args = parser.parse_args()

    password = ""
    for name in ("SCENIC_DEMO_PASSWORD", "SCENIC_ACCOUNT_PASSWORD", "SCENIC_E2E_PASSWORD"):
        password = os.environ.get(name, "").strip()
        if password:
            break
    if not password:
        raise SystemExit("Set SCENIC_DEMO_PASSWORD before importing")

    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    # 同一来源会命中多个检索主题；向量索引按来源唯一，这里按 URL 去重后只导入一次。
    entries: list[dict] = []
    seen_sources: set[str] = set()
    for record in raw.get("queries", []):
        for result in record.get("results", []):
            if not (result.get("content") or result.get("snippet")):
                continue
            url = (result.get("url") or "").strip()
            key = url or f"{record['query']}|{result.get('title', '')}"
            if key in seen_sources:
                continue
            seen_sources.add(key)
            entries.append(_entry(record["query"], result))
    if not entries:
        raise SystemExit("no importable sources found in the raw file")

    base = args.base_url.rstrip("/")
    report: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "batches": [], "imported": 0}
    with httpx.Client(timeout=300.0) as client:
        token = client.post(
            f"{base}/api/v1/auth/login",
            json={"username": args.username, "password": password},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        for start in range(0, len(entries), args.batch_size):
            batch = entries[start : start + args.batch_size]
            response = client.post(
                f"{base}/api/v1/admin/knowledge/import",
                json={"entries": batch},
                headers=headers,
            )
            if response.status_code >= 400:
                if response.status_code == 409:
                    # 已导入过的来源按批次拆分重试，跳过冲突条目后继续。
                    imported = 0
                    skipped: list[str] = []
                    for item in batch:
                        single = client.post(
                            f"{base}/api/v1/admin/knowledge/import",
                            json={"entries": [item]},
                            headers=headers,
                        )
                        if single.status_code == 409:
                            skipped.append(item.get("source_id") or item.get("title", ""))
                            continue
                        if single.status_code >= 400:
                            report["batches"].append(
                                {"start": start, "error": f"{single.status_code}: {single.text[:200]}"}
                            )
                            break
                        imported += int(single.json().get("imported", 0))
                    report["imported"] += imported
                    report["batches"].append({"start": start, "imported": imported, "skipped": skipped})
                    print(f"batch {start // args.batch_size + 1}: imported {imported}, skipped {len(skipped)}")
                    continue
                report["batches"].append({"start": start, "error": f"{response.status_code}: {response.text[:200]}"})
                break
            payload = response.json()
            report["imported"] += int(payload.get("imported", 0))
            report["batches"].append({"start": start, "batch_id": payload.get("batch_id"), "imported": payload.get("imported")})
            print(f"batch {start // args.batch_size + 1}: imported {payload.get('imported')}")

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"imported": report["imported"], "report": str(args.report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
