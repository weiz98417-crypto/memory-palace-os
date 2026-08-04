from __future__ import annotations

from src.memory_palace.config.feature_registry import load_feature_registry, registry_snapshot
from src.memory_palace.config.integration_readiness import wechat_integration_readiness


def test_real_wecom_stays_disabled_by_policy_even_when_credentials_exist(monkeypatch):
    for key, value in {
        "WECHAT_TOKEN": "configured-token",
        "WECHAT_ENCODING_AES_KEY": "a" * 43,
        "WECHAT_CORP_ID": "configured-corp",
        "WECHAT_CORP_SECRET": "configured-secret",
        "WECHAT_AGENT_ID": "1000002",
    }.items():
        monkeypatch.setenv(key, value)

    readiness = wechat_integration_readiness()

    assert readiness == {
        "configured": False,
        "status": "DISABLED_BY_POLICY",
        "missing": [],
        "safe_disabled_verified": True,
        "policy_mode": "WECOM_SIMULATOR_ONLY",
        "blocked_reason": "本项目仅允许企业内部系统接入环境，生产外部渠道收发已按项目策略禁用。",
    }


def test_real_wecom_client_factory_never_initializes_transport(monkeypatch):
    import src.memory_palace.tools.wechat_client as wechat_module

    for key, value in {
        "WECHAT_CORP_ID": "configured-corp",
        "WECHAT_CORP_SECRET": "configured-secret",
        "WECHAT_AGENT_ID": "1000002",
    }.items():
        monkeypatch.setenv(key, value)

    def fail_if_initialized(**_kwargs):
        raise AssertionError("real WeCom transport must not be initialized")

    monkeypatch.setattr(wechat_module, "_wechat_client", None)
    monkeypatch.setattr(wechat_module, "WeChatWorkClient", fail_if_initialized)

    assert wechat_module.get_wechat_client() is None


def test_real_wecom_client_cannot_be_constructed_directly():
    import src.memory_palace.tools.wechat_client as wechat_module

    try:
        wechat_module.WeChatWorkClient(
            corpid="configured-corp",
            corpsecret="configured-secret",
            agentid=1000002,
        )
    except RuntimeError as exc:
        assert "企业内部系统接入环境" in str(exc)
    else:
        raise AssertionError("real WeCom transport must reject direct construction")


def test_registry_treats_real_wecom_safe_disable_as_satisfied_but_never_ready():
    registry = load_feature_registry()
    declared = next(item for item in registry["items"] if item["id"] == "MVP-INTEGRATION-WECHAT")
    assert declared["name"] == "生产外部渠道安全禁用门禁"
    assert declared["status"] == "DISABLED_BY_POLICY"

    snapshot = registry_snapshot(
        evidence={
            "integrations": {
                "wechat": {
                    "configured": False,
                    "status": "DISABLED_BY_POLICY",
                    "live_verified": False,
                    "safe_disabled_verified": True,
                    "policy_mode": "WECOM_SIMULATOR_ONLY",
                }
            }
        }
    )
    item = next(entry for entry in snapshot["items"] if entry["id"] == "MVP-INTEGRATION-WECHAT")

    assert item["status"] == "DISABLED_BY_POLICY"
    assert item["safe_disabled_verified"] is True
    assert item["acceptance"]["missing"] == []
    assert item["status"] != "READY"
