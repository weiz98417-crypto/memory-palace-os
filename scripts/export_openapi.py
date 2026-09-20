"""Export the FastAPI OpenAPI document for the frontend build.

The frontend build must not depend on a live server during Docker image construction.
This entrypoint imports the real application with build-only placeholder secrets,
writes the canonical OpenAPI document to a file, and lets the frontend type check
consume that file.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_BUILD_DEFAULTS = {
    "DEMO_MODE": "false",
    "APP_ENV": "prod",
    "DEEPSEEK_API_KEY": "build-openapi-placeholder-key",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
    "LLM_DEFAULT_MODEL": "deepseek-flash",
    "DATABASE_URL": "postgresql://build:build@localhost:5432/build",
    "REDIS_URL": "redis://localhost:6379/0",
    "MEMORY_PALACE_JWT_SECRET": "build-openapi-placeholder-jwt-secret-32chars",
    "ADMIN_PASSWORD": "build-openapi-password",
}


def _apply_build_defaults() -> None:
    # The exported contract must not vary with a developer's shell or .env file.
    for key, value in _BUILD_DEFAULTS.items():
        os.environ[key] = value


def main() -> int:
    _apply_build_defaults()
    from main import app

    output = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
