from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APPS: dict[str, dict[str, str]] = {
    "console": {
        "route": "/admin/",
        "v2": "/admin/assets/index-",
        "legacy": 'id="view-dashboard"',
    },
    "field": {
        "route": "/assistant/",
        "v2": "/assistant/assets/index-",
        "legacy": 'id="app-screen"',
    },
    "integration": {
        "route": "/simulator/wecom/",
        "v2": "/simulator/wecom/assets/index-",
        "legacy": "/simulator/wecom/app.js",
    },
    "operations": {
        "route": "/operations/scenic/",
        "v2": "/operations/assets/index-",
        "legacy": "/operations/scenic/app.js",
    },
}
ALL_APPS = tuple(APPS)
CUTOVER_ORDER = ("operations", "integration", "console", "field")


def fetch_html(base_url: str, route: str, *, timeout: float = 10.0) -> str:
    request = urllib.request.Request(f"{base_url.rstrip('/')}{route}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def classify(app_name: str, html: str) -> str:
    marker = APPS[app_name]
    if marker["v2"] in html:
        return "v2"
    if marker["legacy"] in html:
        return "legacy"
    return "unknown"


def compose_restart(args: argparse.Namespace, apps: tuple[str, ...]) -> None:
    env = os.environ.copy()
    env["FRONTEND_V2_APPS"] = ",".join(apps)
    command = [
        "docker",
        "compose",
        "-p",
        args.project,
        "--env-file",
        args.env_file,
        "-f",
        args.compose_file,
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        args.service,
    ]
    subprocess.run(command, cwd=args.repo_root, env=env, check=True)
    wait_healthy(args)


def wait_healthy(args: argparse.Namespace) -> None:
    deadline = time.monotonic() + args.health_timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", args.container],
            cwd=args.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip() == "healthy":
            return
        time.sleep(1)
    raise RuntimeError(f"container did not become healthy: {args.container}")


def verify_phase(args: argparse.Namespace, expected: dict[str, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for app_name in ALL_APPS:
        html = fetch_html(args.base_url, APPS[app_name]["route"])
        actual = classify(app_name, html)
        records.append(
            {
                "app": app_name,
                "route": APPS[app_name]["route"],
                "expected": expected[app_name],
                "actual": actual,
                "passed": actual == expected[app_name],
            }
        )
    failed = [record for record in records if not record["passed"]]
    if failed:
        raise RuntimeError(f"route classification mismatch: {failed}")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise every frontend V2 rollback state.")
    parser.add_argument("--mode", choices=("rollback", "cutover"), default="rollback")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--project", default="memory-palace-scenic")
    parser.add_argument("--compose-file", default="deploy/docker-compose.yml")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--service", default="app")
    parser.add_argument("--container", default="memory-palace-scenic-app-1")
    parser.add_argument("--health-timeout", type=float, default=90.0)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("artifacts/frontend-v2/rollback-drill.json"),
    )
    args = parser.parse_args()
    args.repo_root = Path(__file__).resolve().parents[1]

    phases: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
    if args.mode == "cutover":
        enabled: list[str] = []
        phases.append(("legacy-baseline", (), {app: "legacy" for app in ALL_APPS}))
        for target in CUTOVER_ORDER:
            enabled.append(target)
            phases.append(
                (
                    f"enable-{target}",
                    tuple(enabled),
                    {app: ("v2" if app in enabled else "legacy") for app in ALL_APPS},
                )
            )
    else:
        phases.append(("all-legacy", (), {app: "legacy" for app in ALL_APPS}))
        for target in ALL_APPS:
            phases.append(
                (
                    f"v2-{target}-only",
                    (target,),
                    {app: ("v2" if app == target else "legacy") for app in ALL_APPS},
                )
            )
        phases.append(("all-v2", ALL_APPS, {app: "v2" for app in ALL_APPS}))
        for target in ALL_APPS:
            phases.append(
                (
                    f"rollback-{target}",
                    tuple(app for app in ALL_APPS if app != target),
                    {app: ("legacy" if app == target else "v2") for app in ALL_APPS},
                )
            )

    evidence: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "base_url": args.base_url,
        "phases": [],
        "passed": False,
    }
    try:
        previous: tuple[str, ...] = ()
        for name, enabled, expected in phases:
            started_at = datetime.now(timezone.utc).isoformat()
            compose_restart(args, enabled)
            records = verify_phase(args, expected)
            evidence["phases"].append(
                {
                    "name": name,
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "frontend_v2_apps": ",".join(enabled),
                    "rollback_frontend_v2_apps": ",".join(previous),
                    "routes": records,
                }
            )
            previous = enabled
        evidence["passed"] = True
    finally:
        compose_restart(args, ALL_APPS)
        evidence["restored"] = {
            "frontend_v2_apps": ",".join(ALL_APPS),
            "healthy": True,
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not evidence["passed"]:
        raise SystemExit(f"frontend {args.mode} drill failed")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
