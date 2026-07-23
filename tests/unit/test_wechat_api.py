"""
企微 API 单元测试 (Unit Test for WeChat Client)

当前 API：异步 httpx.AsyncClient + asyncio Lock

测试核心：
  1. Token 生命周期：获取/缓存/过期刷新
  2. 40014 自动重试：Token 失效后自动刷新并重发
  3. DCL 锁：并发获取 Token 只触发一次网络请求

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock

from src.memory_palace.tools.wechat_client import WeChatWorkClient


CORP_ID     = "ww_test_id"
CORP_SECRET = "test_secret"
AGENT_ID    = 10001

GET_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
SEND_MSG_URL  = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

MOCK_TOKEN_V1 = "MOCK_TOKEN_FIRST"
MOCK_TOKEN_V2 = "NEW_VALID_TOKEN_AFTER_REFRESH"


@pytest.fixture
def wx_client():
    client = WeChatWorkClient(corpid=CORP_ID, corpsecret=CORP_SECRET, agentid=AGENT_ID)
    client._access_token = None
    client._token_expires_at = 0.0
    return client


def _mock_resp(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


def _token_resp(token: str = MOCK_TOKEN_V1, expires_in: int = 7200):
    return _mock_resp({"errcode": 0, "errmsg": "ok", "access_token": token, "expires_in": expires_in})


class TestTokenLifecycle:

    @pytest.mark.asyncio
    async def test_first_fetch_succeeds_and_caches(self, wx_client):
        """首次获取 Token 成功并缓存"""
        wx_client.client.get = AsyncMock(return_value=_token_resp(MOCK_TOKEN_V1))

        token = await wx_client._get_access_token()

        assert token == MOCK_TOKEN_V1
        assert wx_client._access_token == MOCK_TOKEN_V1
        assert wx_client._token_expires_at > time.time()
        assert wx_client.client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_cached_token_not_refetched(self, wx_client):
        """缓存有效时不重复请求"""
        call_count = 0

        async def _get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _token_resp(MOCK_TOKEN_V1)

        wx_client.client.get = _get

        await wx_client._get_access_token()
        await wx_client._get_access_token()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_expired_local_token_triggers_refresh(self, wx_client):
        """本地过期后自动刷新"""
        wx_client._access_token = "EXPIRED_TOKEN"
        wx_client._token_expires_at = time.time() - 1

        wx_client.client.get = AsyncMock(return_value=_token_resp(MOCK_TOKEN_V2))
        token = await wx_client._get_access_token()

        assert token == MOCK_TOKEN_V2

    @pytest.mark.asyncio
    async def test_token_fetch_failure_raises(self, wx_client):
        """腾讯返回错误码时抛出异常"""
        wx_client.client.get = AsyncMock(return_value=_mock_resp({"errcode": 40013, "errmsg": "invalid corpid"}))

        with pytest.raises(Exception, match="40013|corpid|Token"):
            await wx_client._get_access_token()


class TestAutoRetryOn40014:

    @pytest.mark.asyncio
    async def test_send_text_retries_after_40014(self, wx_client):
        """40014 自动刷新 Token 并重试"""
        post_call_count = 0

        async def _post(url, *args, **kwargs):
            nonlocal post_call_count
            post_call_count += 1
            if post_call_count == 1:
                return _mock_resp({"errcode": 40014, "errmsg": "access_token expired"})
            return _mock_resp({"errcode": 0, "errmsg": "ok"})

        wx_client.client.post = _post
        wx_client.client.get = AsyncMock(return_value=_token_resp(MOCK_TOKEN_V2))

        wx_client._access_token = "OLD_EXPIRED_TOKEN"
        wx_client._token_expires_at = time.time() + 3600

        success = await wx_client.send_text("user_a", "Hello World")

        assert success is True
        assert post_call_count == 2

    @pytest.mark.asyncio
    async def test_retry_only_once_on_40014(self, wx_client):
        """连续 40014 不无限重试"""
        wx_client.client.post = AsyncMock(return_value=_mock_resp({"errcode": 40014, "errmsg": "expired"}))
        wx_client.client.get = AsyncMock(return_value=_token_resp(MOCK_TOKEN_V2))

        wx_client._access_token = "OLD_EXPIRED_TOKEN"
        wx_client._token_expires_at = time.time() + 3600

        success = await wx_client.send_text("user_a", "Hello")
        assert success is False


class TestDCLLock:

    @pytest.mark.asyncio
    async def test_concurrent_token_fetch_only_calls_api_once(self, wx_client):
        """DCL 锁：10 个协程同时请求，API 只调用 1 次"""
        call_count = 0

        async def _slow_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.02)
            return _token_resp("CONCURRENT_TOKEN")

        wx_client.client.get = _slow_get
        wx_client._access_token = None
        wx_client._token_expires_at = 0.0

        async def fetch():
            return await wx_client._get_access_token()

        tokens = await asyncio.gather(*[fetch() for _ in range(10)])

        assert call_count == 1, f"DCL 锁失效：10 个协程触发了 {call_count} 次 API 调用"
        assert all(t == "CONCURRENT_TOKEN" for t in tokens)
        assert len(tokens) == 10

    @pytest.mark.asyncio
    async def test_lock_released_after_exception(self, wx_client):
        """异常后锁正确释放"""
        get_call_count = 0

        async def _flaky_get(*args, **kwargs):
            nonlocal get_call_count
            get_call_count += 1
            if get_call_count == 1:
                raise ConnectionError("模拟网络抖动")
            return _token_resp("RECOVERED_TOKEN")

        wx_client.client.get = _flaky_get
        wx_client._access_token = None
        wx_client._token_expires_at = 0.0

        with pytest.raises(Exception):
            await wx_client._get_access_token()

        token = await wx_client._get_access_token()
        assert token == "RECOVERED_TOKEN"
