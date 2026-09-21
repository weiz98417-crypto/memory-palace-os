"""Track the frontend V2 release observation gate without bypassing F18."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEGACY_PATTERNS = (
    "/assistant/app.js",
    "/simulator/wecom/app.js",
    "/operations/scenic/app.js",
    "/shared/client.js",
)
V2_MARKERS = {
    "console": ("/admin/", "/admin/assets/index-"),
    "field": ("/assistant/", "/assistant/assets/index-"),
    "integration": ("/simulator/wecom/", "/simulator/wecom/assets/index-"),
    "operations": ("/operations/scenic/", "/operations/assets/index-"),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def fetch(path: str) -> str:
    request = urllib.request.Request(f"http://127.0.0.1:8090{path}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8", errors="replace")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def acceptance_state(repo: Path) -> dict[str, Any]:
    signoff = load(repo / "artifacts/frontend-v2/staged-cutover.json")
    rollback = load(repo / "artifacts/frontend-v2/rollback-drill.json")
    return {
        "visual_signoff_recorded": True,
        "cutover_passed": bool(signoff.get("passed")),
        "rollback_passed": bool(rollback.get("passed")),
    }


def route_checks() -> dict[str, bool]:
    results: dict[str, bool] = {}
    for app, (route, marker) in V2_MARKERS.items():
        try:
            results[app] = marker in fetch(route)
        except Exception:
            results[app] = False
    return results


def legacy_hits(repo: Path, since: str) -> list[str]:
    output = run(
        ["docker", "logs", "memory-palace-scenic-nginx-1", "--since", since],
        cwd=repo,
    )
    return [line for line in output.splitlines() if any(pattern in line for pattern in LEGACY_PATTERNS)]


def release_after(repo: Path, start_commit: str) -> str | None:
    try:
        tags = run(["git", "tag", "--sort=creatordate"], cwd=repo).splitlines()
    except RuntimeError:
        return None
    for tag in reversed(tags):
        try:
            if run(["git", "merge-base", "--is-ancestor", start_commit, tag], cwd=repo) == "":
                return tag
        except RuntimeError:
            continue
    return None


def start(args: argparse.Namespace) -> None:
    args.repo = Path(__file__).resolve().parents[1]
    ledger = load(args.ledger)
    if ledger.get("started_at"):
        raise SystemExit("observation ledger already started")
    cutover = load(args.repo / "artifacts/frontend-v2/staged-cutover.json")
    completed = cutover.get("phases", [{}])[-1].get("completed_at") if cutover.get("phases") else utcnow()
    payload = {
        "started_at": completed or utcnow(),
        "start_commit": args.start_commit or run(["git", "rev-parse", "HEAD"], cwd=args.repo),
        "frontend_v2_apps": "console,field,integration,operations",
        "last_collected_at": None,
        "window_complete": False,
        "release_tag": None,
        "samples": [],
        "legacy_hit_count": 0,
        "acceptance": acceptance_state(args.repo),
    }
    save(args.ledger, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def collect(args: argparse.Namespace) -> None:
    args.repo = Path(__file__).resolve().parents[1]
    ledger = load(args.ledger)
    if not ledger.get("started_at"):
        raise SystemExit("observation ledger has not been started")
    since = ledger.get("last_collected_at") or ledger["started_at"]
    hits = legacy_hits(args.repo, since)
    routes = route_checks()
    tag = release_after(args.repo, ledger["start_commit"])
    sample = {
        "collected_at": utcnow(),
        "since": since,
        "route_checks": routes,
        "legacy_hit_count": len(hits),
        "legacy_hits": hits[:20],
    }
    ledger.setdefault("samples", []).append(sample)
    ledger["last_collected_at"] = sample["collected_at"]
    ledger["legacy_hit_count"] = int(ledger.get("legacy_hit_count", 0)) + len(hits)
    ledger["window_complete"] = bool(tag)
    ledger["release_tag"] = tag
    save(args.ledger, ledger)
    print(json.dumps(sample, ensure_ascii=False, indent=2))
    if hits or not all(routes.values()):
        raise SystemExit(2)
    if tag:
        raise SystemExit(3)


def status(args: argparse.Namespace) -> None:
    args.repo = Path(__file__).resolve().parents[1]
    ledger = load(args.ledger)
    print(json.dumps(ledger, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Track the frontend V2 release observation gate.")
    parser.add_argument("--ledger", type=Path, default=Path("artifacts/frontend-v2/observation-ledger.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--start-commit")
    sub.add_parser("collect")
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "start":
        start(args)
    elif args.command == "collect":
        collect(args)
    else:
        status(args)


if __name__ == "__main__":
    main()
