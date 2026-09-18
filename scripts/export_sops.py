"""Export the venue's SOPs (default: the published ones) to JSON for archiving."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SCENIC_DEMO_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--username", default="wangfang")
    parser.add_argument("--ids", default="", help="comma separated SOP ids; empty means all")
    parser.add_argument("--status", default="PUBLISHED")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "artifacts" / "knowledge" / "sops-export.json")
    args = parser.parse_args()

    password = ""
    for name in ("SCENIC_DEMO_PASSWORD", "SCENIC_ACCOUNT_PASSWORD", "SCENIC_E2E_PASSWORD"):
        password = os.environ.get(name, "").strip()
        if password:
            break
    if not password:
        raise SystemExit("Set SCENIC_DEMO_PASSWORD before exporting")

    with httpx.Client(timeout=60.0) as client:
        token = client.post(
            f"{args.base_url.rstrip('/')}/api/v1/auth/login",
            json={"username": args.username, "password": password},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        sops = client.get(f"{args.base_url.rstrip('/')}/api/v1/admin/sops", headers=headers).json()["sops"]

    wanted = {int(part) for part in args.ids.split(",") if part.strip()}
    selected = [
        item
        for item in sops
        if (not wanted or int(item["id"]) in wanted)
        and (not args.status or item.get("status") == args.status)
    ]
    document = {
        "note": "导出留档：内容与系统中已发布版本一致。",
        "base_url": args.base_url,
        "count": len(selected),
        "entries": [
            {
                "id": item["id"],
                "title": item["title"],
                "category": item["category"],
                "priority": item.get("priority"),
                "version": item.get("version"),
                "status": item.get("status"),
                "content": item["content"],
            }
            for item in selected
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported {len(selected)} SOPs -> {args.output}")


if __name__ == "__main__":
    main()
