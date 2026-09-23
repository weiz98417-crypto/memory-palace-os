"""Behind a reverse proxy the app must opt in before trusting forwarding headers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBE = (
    "import main;"
    "print([(str(entry.cls), entry.kwargs) for entry in main.app.user_middleware "
    "if 'ProxyHeaders' in str(entry.cls)])"
)


def _probe_proxy_headers(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DEMO_MODE": "true",
        "TRUST_PROXY_HEADERS": "",
        "TRUSTED_PROXY_HOSTS": "",
        **extra_env,
    }
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result


def test_proxy_headers_stay_untrusted_by_default():
    result = _probe_proxy_headers({})
    assert result.returncode == 0, result.stderr[-1000:]
    assert result.stdout.strip().splitlines()[-1] == "[]"


def test_proxy_headers_are_trusted_when_the_deployment_opts_in():
    result = _probe_proxy_headers(
        {
            "TRUST_PROXY_HEADERS": "true",
            "TRUSTED_PROXY_HOSTS": "127.0.0.1,10.0.0.0/8",
        }
    )
    assert result.returncode == 0, result.stderr[-1000:]
    middleware = result.stdout.strip().splitlines()[-1]
    assert "127.0.0.1" in middleware
    assert "10.0.0.0/8" in middleware
    assert "'*'" not in middleware


def test_proxy_header_opt_in_requires_explicit_trusted_sources():
    result = _probe_proxy_headers({"TRUST_PROXY_HEADERS": "true"})

    assert result.returncode != 0
    assert "TRUSTED_PROXY_HOSTS" in result.stderr
