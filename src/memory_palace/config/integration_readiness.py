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
REAL_WECOM_POLICY_MODE = "WECOM_SIMULATOR_ONLY"
REAL_WECOM_BLOCKED_REASON = "本项目仅允许企微模拟器，真实企业微信收发已按项目策略禁用。"


def external_integration_readiness(required: Iterable[str]) -> dict[str, object]:
    missing = [key for key in required if not os.environ.get(key, "").strip()]
    configured = not missing
    return {
        "configured": configured,
        "status": "BLOCKED" if configured else "DISABLED_REQUIRES_CONFIG",
        "missing": missing,
    }


def wechat_integration_readiness() -> dict[str, object]:
    return {
        "configured": False,
        "status": "DISABLED_BY_POLICY",
        "missing": [],
        "safe_disabled_verified": True,
        "policy_mode": REAL_WECOM_POLICY_MODE,
        "blocked_reason": REAL_WECOM_BLOCKED_REASON,
    }
