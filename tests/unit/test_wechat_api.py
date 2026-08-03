"""Policy tests for the disabled real WeCom transport compatibility module."""

from __future__ import annotations

import pytest

from src.memory_palace.config.integration_readiness import REAL_WECOM_BLOCKED_REASON
from src.memory_palace.tools.wechat_client import WeChatWorkClient, get_wechat_client


def test_direct_real_wecom_client_construction_is_rejected():
    with pytest.raises(RuntimeError, match="企微模拟器"):
        WeChatWorkClient(corpid="configured", corpsecret="configured", agentid=10001)


def test_real_wecom_client_factory_returns_no_transport():
    assert get_wechat_client() is None
    assert "真实企业微信" in REAL_WECOM_BLOCKED_REASON
