"""Import curated SOP documents through the formal SOP lifecycle.

Each entry becomes a draft, is submitted for review, and is published by a manager
account. Publishing is what writes the ``source_type=SOP`` vector, so the imported
content is usable by the scenic SOP retrieval without touching the database directly.

Input format (JSON):

    {
      "entries": [
        {
          "title": "...",
          "category": "设备与客流联动",
          "content": "... 来源：<url>（<title>，检索于 YYYY-MM-DD）",
          "priority": 1,
          "version": "1.0",
          "tags": ["观光车", "雨后复运"],
          "source_url": "https://..."
        }
      ]
    }

Usage::

    $env:SCENIC_DEMO_PASSWORD = '<demo password>'
    uv run --with httpx python scripts/import_sops.py --input artifacts/knowledge/sops.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ImportError_(RuntimeError):
    pass


def _login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    response = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    if response.status_code >= 400:
        raise ImportError_(f"login failed for {username}: {response.status_code}")
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _existing_titles(client: httpx.Client, base_url: str, token: str) -> dict[str, dict[str, Any]]:
    response = client.get(f"{base_url}/api/v1/admin/sops", headers=_headers(token))
    response.raise_for_status()
    return {item["title"]: item for item in response.json().get("sops", [])}


def _sop_id(payload: dict[str, Any]) -> int:
    for key in ("id", "sop_id"):
        if key in payload:
            return int(payload[key])
    sop = payload.get("sop")
    if isinstance(sop, dict) and "id" in sop:
        return int(sop["id"])
    raise ImportError_(f"cannot find SOP id in response: {sorted(payload)}")


def import_entries(
    *,
    base_url: str,
    username: str,
    password: str,
    entries: list[dict[str, Any]],
    reviewer_note: str,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "imported_by": username,
        "entries": [],
    }
    with httpx.Client(timeout=120.0) as client:
        token = _login(client, base_url, username, password)
        existing = _existing_titles(client, base_url, token)

        for entry in entries:
            title = str(entry["title"]).strip()
            record: dict[str, Any] = {"title": title, "source_url": entry.get("source_url", "")}
            current = existing.get(title)
            if current is not None:
                record.update(
                    {
                        "sop_id": current.get("id"),
                        "status": current.get("status"),
                        "outcome": "skipped_existing",
                    }
                )
                report["entries"].append(record)
                continue

            create = client.post(
                f"{base_url}/api/v1/admin/sops",
                json={
                    "title": title,
                    "content": str(entry["content"]).strip(),
                    "category": str(entry.get("category") or "通用")[:80],
                    "priority": int(entry.get("priority", 2)),
                    "version": str(entry.get("version") or "1.0"),
                },
                headers=_headers(token),
            )
            if create.status_code >= 400:
                record.update({"outcome": "failed", "error": f"create {create.status_code}: {create.text[:200]}"})
                report["entries"].append(record)
                continue
            sop_id = _sop_id(create.json())
            record["sop_id"] = sop_id

            for step in ("submit", "publish"):
                response = client.post(
                    f"{base_url}/api/v1/admin/sops/{sop_id}/{step}",
                    json={"comment": reviewer_note},
                    headers=_headers(token),
                )
                if response.status_code >= 400:
                    record.update(
                        {
                            "outcome": "failed",
                            "error": f"{step} {response.status_code}: {response.text[:200]}",
                        }
                    )
                    break
            else:
                detail = client.get(
                    f"{base_url}/api/v1/admin/sops/{sop_id}", headers=_headers(token)
                )
                status = detail.json().get("sop", {}).get("status") if detail.status_code == 200 else None
                record.update({"status": status, "outcome": "published"})
            report["entries"].append(record)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["published"] = sum(1 for item in report["entries"] if item.get("outcome") == "published")
    report["skipped"] = sum(1 for item in report["entries"] if item.get("outcome") == "skipped_existing")
    report["failed"] = sum(1 for item in report["entries"] if item.get("outcome") == "failed")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON file with the SOP entries")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SCENIC_DEMO_BASE_URL", "http://127.0.0.1:8090"),
    )
    parser.add_argument("--username", default="wangfang", help="manager/admin account that publishes")
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "knowledge" / "sop-import-report.json",
    )
    parser.add_argument("--reviewer-note", default="知识导入：已核对公开来源后发布")
    args = parser.parse_args()

    password = ""
    for name in ("SCENIC_DEMO_PASSWORD", "SCENIC_ACCOUNT_PASSWORD", "SCENIC_E2E_PASSWORD"):
        password = os.environ.get(name, "").strip()
        if password:
            break
    if not password:
        raise SystemExit("Set SCENIC_DEMO_PASSWORD before importing")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not entries:
        raise SystemExit("input file contains no entries")

    report = import_entries(
        base_url=args.base_url.rstrip("/"),
        username=args.username,
        password=password,
        entries=list(entries),
        reviewer_note=args.reviewer_note,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "published": report["published"],
                "skipped": report["skipped"],
                "failed": report["failed"],
                "report": str(args.report),
            },
            ensure_ascii=False,
        )
    )
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
