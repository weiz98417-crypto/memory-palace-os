"""Behind a reverse proxy the app must opt in before trusting forwarding headers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBE = (
    "import main;"
    "print(any('ProxyHeaders' in str(entry.cls) for entry in main.app.user_middleware))"
)


def _proxy_headers_trusted(extra_env: dict[str, str]) -> bool:
    env = {**os.environ, "DEMO_MODE": "true", "TRUST_PROXY_HEADERS": "", **extra_env}
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr[-1000:]
    return result.stdout.strip().splitlines()[-1] == "True"


def test_proxy_headers_stay_untrusted_by_default():
    assert _proxy_headers_trusted({}) is False


def test_proxy_headers_are_trusted_when_the_deployment_opts_in():
    assert _proxy_headers_trusted({"TRUST_PROXY_HEADERS": "true"}) is True
