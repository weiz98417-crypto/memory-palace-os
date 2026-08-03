"""Shared readiness rules for external channel integrations."""

from __future__ import annotations

import os
from typing import Iterable


WECHAT_REQUIRED_CONFIG = (
    "WECHAT_TOKEN",
    "WECHAT_ENCODING_AES_KEY",
    "WECHAT_CORP_ID",
    "WECHAT_CORP_SECRET",
    "WECHAT_AGENT_ID",
)


def external_integration_readiness(required: Iterable[str]) -> dict[str, object]:
    missing = [key for key in required if not os.environ.get(key, "").strip()]
    configured = not missing
    return {
        "configured": configured,
        "status": "BLOCKED" if configured else "DISABLED_REQUIRES_CONFIG",
        "missing": missing,
    }


def wechat_integration_readiness() -> dict[str, object]:
    return external_integration_readiness(WECHAT_REQUIRED_CONFIG)
