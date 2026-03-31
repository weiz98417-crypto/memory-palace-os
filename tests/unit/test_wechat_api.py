"""
企微 API 单元测试 (Unit Test for WeChat Client)

测试核心：验证 wechat_client.py 中的 DCL 锁 和 Token 自动重试逻辑。

工业级测试要点：
  1. Mock 网络请求：使用 requests-mock 拦截所有外发 HTTP 请求，零真实网络依赖
  2. 状态机测试：模拟 Token 过期 (40014) 场景，验证自动刷新并重发链路
  3. DCL 锁测试：验证并发获取 Token 时只触发一次网络调用（Double-Checked Locking）
  4. 边界测试：Token 本地过期检测、接口异常兜底

原始模板 Bug 修复说明：
  - 原 assert "NEW_VALID_TOKEN" in m.request_history[-1].url
    → Token 在 URL query string 中，应用 urllib.parse 解析后再断言
  - 原代码缺少 DCL 锁并发测试，本文件已补全
"""

import threading
import time
from unittest.mock import patch

import pytest
import requests_mock as requests_mock_module

from src.memory_palace.tools.wechat_client import WeChatWorkClient

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fixtures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CORP_ID     = "ww_test_id"
CORP_SECRET = "test_secret"
AGENT_ID    = 10001

GET_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
SEND_MSG_URL  = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

MOCK_TOKEN_V1 = "MOCK_TOKEN_FIRST"
MOCK_TOKEN_V2 = "NEW_VALID_TOKEN_AFTER_REFRESH"


@pytest.fixture
def wx_client():
    """每个测试用例得到一个全新的、状态清空的客户端实例"""
    client = WeChatWorkClient(
        corpid=CORP_ID,
        corpsecret=CORP_SECRET,
        agentid=AGENT_ID,
    )
    # 确保初始状态干净，不带任何缓存 Token
    client._access_token = None
    client._token_expires_at = 0.0
    return client


def _mock_token_response(token: str = MOCK_TOKEN_V1, expires_in: int = 7200) -> dict:
    return {"errcode": 0, "errmsg": "ok", "access_token": token, "expires_in": expires_in}


def _extract_token_from_request(request) -> str:
    """从请求 URL 的 query string 中提取 access_token 参数"""
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(request.url).query)
    return qs.get("access_token", [""])[0]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Token 基础生命周期测试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTokenLifecycle:

    def test_first_fetch_succeeds_and_caches(self, wx_client):
        """首次获取 Token 成功，并正确写入本地缓存"""
        with requests_mock_module.Mocker() as m:
            m.get(GET_TOKEN_URL, json=_mock_token_response(MOCK_TOKEN_V1))

            token = wx_client._get_access_token()

            assert token == MOCK_TOKEN_V1
            assert wx_client._access_token == MOCK_TOKEN_V1
            assert wx_client._token_expires_at > time.time()
            assert m.call_count == 1, "首次获取应只发起一次网络请求"

    def test_cached_token_not_refetched(self, wx_client):
        """本地 Token 未过期时，连续调用不发起网络请求"""
        with requests_mock_module.Mocker() as m:
            m.get(GET_TOKEN_URL, json=_mock_token_response(MOCK_TOKEN_V1))

            # 第一次：网络获取
            wx_client._get_access_token()
            # 第二次：应命中缓存
            token = wx_client._get_access_token()

            assert token == MOCK_TOKEN_V1
            assert m.call_count == 1, "有效缓存期内不应重复发起网络请求"

    def test_expired_local_token_triggers_refresh(self, wx_client):
        """本地 Token 过期后，自动触发重新获取"""
        with requests_mock_module.Mocker() as m:
            m.get(GET_TOKEN_URL, json=_mock_token_response(MOCK_TOKEN_V2))

            # 手动注入一个已过期的 Token
            wx_client._access_token = "EXPIRED_TOKEN"
            wx_client._token_expires_at = time.time() - 1  # 已过期 1 秒

            token = wx_client._get_access_token()

            assert token == MOCK_TOKEN_V2, "过期后应自动刷新并返回新 Token"
            assert m.call_count == 1

    def test_token_fetch_failure_raises(self, wx_client):
        """腾讯接口返回错误时，应抛出可识别的异常而非静默吞错"""
        with requests_mock_module.Mocker() as m:
            m.get(GET_TOKEN_URL, json={"errcode": 40013, "errmsg": "invalid corpid"})

            with pytest.raises(Exception, match="40013|corpid|Token"):
                wx_client._get_access_token()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Token 40014 自动重试链路测试（状态机核心）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAutoRetryOn40014:

    def test_send_text_retries_after_40014(self, wx_client):
        """
        【核心链路】发送消息遇到 40014 (Token 失效)，自动刷新并重发，最终成功。
        完整链路：
          发送(旧Token, 失败40014) → 清空缓存 → 重新获取Token → 再次发送(新Token, 成功)
        """
        with requests_mock_module.Mocker() as m:
            # 发送接口：第一次 40014，第二次成功
            m.post(SEND_MSG_URL, [
                {"json": {"errcode": 40014, "errmsg": "access_token expired"}},
                {"json": {"errcode": 0,     "errmsg": "ok"}},
            ])
            # Token 刷新接口
            m.get(GET_TOKEN_URL, json=_mock_token_response(MOCK_TOKEN_V2))

            # 注入一个"本地看起来有效但服务端已失效"的旧 Token
            wx_client._access_token = "OLD_EXPIRED_TOKEN"
            wx_client._token_expires_at = time.time() + 3600  # 本地未过期

            success = wx_client.send_text("user_a", "Hello World")

            assert success is True, "重试后应返回成功"
            assert m.call_count == 3, "应有 3 次请求：1次发送失败 + 1次刷新Token + 1次重发"

            # 验证第一次发送用的是旧 Token
            first_send = m.request_history[0]
            assert _extract_token_from_request(first_send) == "OLD_EXPIRED_TOKEN"

            # 验证重发时用的是新 Token（修复原模板的 Bug：用 parse_qs 而非 in url）
            last_send = m.request_history[-1]
            assert _extract_token_from_request(last_send) == MOCK_TOKEN_V2

    def test_retry_only_once_on_40014(self, wx_client):
        """
        防止无限重试：连续两次 40014 时，第二次不再重试，直接返回失败。
        避免因 Token 服务永久故障导致死循环。
        """
        with requests_mock_module.Mocker() as m:
            # 发送接口：两次都 40014
            m.post(SEND_MSG_URL, [
                {"json": {"errcode": 40014, "errmsg": "access_token expired"}},
                {"json": {"errcode": 40014, "errmsg": "access_token expired"}},
            ])
            m.get(GET_TOKEN_URL, json=_mock_token_response(MOCK_TOKEN_V2))

            wx_client._access_token = "OLD_EXPIRED_TOKEN"
            wx_client._token_expires_at = time.time() + 3600

            success = wx_client.send_text("user_a", "Hello")

            assert success is False, "连续 40014 时不应无限重试，应返回失败"
            # 发送最多 2 次（不能更多）
            send_calls = [r for r in m.request_history if "message/send" in r.url]
            assert len(send_calls) <= 2, "重试最多触发一次，总发送不超过 2 次"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. DCL 锁并发安全测试（原模板缺失的核心测试）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestDCLLock:

    def test_concurrent_token_fetch_only_calls_api_once(self, wx_client):
        """
        【DCL 锁核心验证】10 个线程同时请求 Token，网络 API 只应被调用 1 次。

        Double-Checked Locking 模式：
          线程1: 检查无缓存 → 加锁 → 再次检查（此时仍无缓存）→ 发起请求 → 写缓存 → 释放锁
          线程2-10: 检查无缓存 → 等待锁 → 获得锁 → 再次检查（已有缓存）→ 直接返回缓存

        如果没有 DCL，10 个线程会并发发起 10 次 Token 请求，
        造成资源浪费且可能触发腾讯限频（Token 接口有调用频率限制）。
        """
        api_call_count = {"n": 0}
        collected_tokens = []
        lock = threading.Lock()

        def slow_token_response(*args, **kwargs):
            """模拟有延迟的 Token 接口，放大并发竞争窗口"""
            with lock:
                api_call_count["n"] += 1
            time.sleep(0.05)  # 50ms 延迟，确保并发线程都能进入竞争区
            import requests
            resp = requests.Response()
            resp.status_code = 200
            resp._content = (
                b'{"errcode":0,"errmsg":"ok",'
                b'"access_token":"CONCURRENT_TOKEN","expires_in":7200}'
            )
            return resp

        with patch("requests.get", side_effect=slow_token_response):
            def fetch():
                token = wx_client._get_access_token()
                collected_tokens.append(token)

            threads = [threading.Thread(target=fetch) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert api_call_count["n"] == 1, (
            f"DCL 锁失效：10 个并发线程触发了 {api_call_count['n']} 次 Token API 调用，"
            f"预期只触发 1 次"
        )
        assert all(t == "CONCURRENT_TOKEN" for t in collected_tokens), \
            "所有线程应获得相同的 Token"
        assert len(collected_tokens) == 10, "所有线程都应成功获取到 Token"

    def test_lock_released_after_exception(self, wx_client):
        """
        锁异常释放验证：Token 获取中途抛异常，锁必须被正确释放，
        否则后续线程会永久死锁。
        """
        call_count = {"n": 0}

        def flaky_api(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("模拟网络抖动")
            import requests
            resp = requests.Response()
            resp.status_code = 200
            resp._content = (
                b'{"errcode":0,"errmsg":"ok",'
                b'"access_token":"RECOVERED_TOKEN","expires_in":7200}'
            )
            return resp

        with patch("requests.get", side_effect=flaky_api):
            # 第一次：应失败
            with pytest.raises(Exception):
                wx_client._get_access_token()

            # 第二次：锁已释放，应成功（若锁未释放此处会超时死锁）
            token = wx_client._get_access_token()
            assert token == "RECOVERED_TOKEN", "锁释放后应能正常重试获取 Token"