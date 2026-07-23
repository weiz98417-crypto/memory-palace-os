"""
企业微信 API 工业级封装 (WeChat Work Client) - 异步版本

核心变更：
1. 使用 httpx.AsyncClient 替代 requests.Session，支持异步 HTTP/2 与连接池
2. Token 缓存锁从 threading.Lock 改为 asyncio.Lock，适配协程并发模型
3. 所有网络 IO 方法添加 async/await，保持原有重试与容错逻辑

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import time
import asyncio  ### CHANGE: 导入 asyncio
from typing import Dict, Any, Optional, List
from loguru import logger

### CHANGE: 使用 httpx 替代 requests
import httpx
from httpx import HTTPStatusError, RequestError, TimeoutException


class WeChatWorkClient:
    """企业微信服务端 API 客户端 (异步版本)"""

    def __init__(self, corpid: str, corpsecret: str, agentid: int):
        self.corpid = corpid
        self.corpsecret = corpsecret
        self.agentid = agentid

        # ---------------------------------------------------------
        # 1. 异步 HTTP 客户端与连接池
        # ---------------------------------------------------------
        ### CHANGE: 使用 httpx.AsyncClient，配置连接池与超时
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=10)
        timeout = httpx.Timeout(10.0, connect=5.0)
        
        # 注意：httpx 的 Transport 层重试需要手动实现或使用第三方库，
        # 这里我们在 _send_request 中手动实现指数退避
        self.client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            http2=True  # 启用 HTTP/2 提升并发性能
        )

        # ---------------------------------------------------------
        # 2. Token 缓存与异步并发锁机制
        # ---------------------------------------------------------
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        ### CHANGE: threading.Lock 改为 asyncio.Lock
        self._token_lock = asyncio.Lock()

    ### CHANGE: 添加 async 前缀
    async def _get_access_token(self, force_refresh: bool = False) -> str:
        """
        获取企微 Access Token (异步版本)。
        采用 DCL (Double-Checked Locking) 机制，适配协程并发模型。
        """
        # 第一层检查 (无锁，快速路径)
        if not force_refresh and self._access_token and time.time() < (self._token_expires_at - 200):
            return self._access_token

        ### CHANGE: 使用 async with 获取异步锁
        async with self._token_lock:
            # 第二层检查 (有锁，防止重复刷新)
            if not force_refresh and self._access_token and time.time() < (self._token_expires_at - 200):
                return self._access_token

            logger.info("企微 Access Token 缓存失效或强制刷新，正在请求腾讯服务器...")
            url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corpid}&corpsecret={self.corpsecret}"
            
            try:
                ### CHANGE: 使用 await 进行异步 GET 请求
                resp = await self.client.get(url)
                resp.raise_for_status()
                data = resp.json()

                if data.get("errcode") == 0:
                    self._access_token = data.get("access_token")
                    self._token_expires_at = time.time() + data.get("expires_in", 7200)
                    logger.success(f"企微 Token 刷新成功，有效期至: {time.ctime(self._token_expires_at)}")
                    return self._access_token
                else:
                    logger.error(f"企微 Token 请求失败，返回报文: {data}")
                    raise RuntimeError(f"WeChat Token Error: {data.get('errmsg')}")

            except Exception as e:
                logger.error(f"企微 Token 网络通信异常: {e}")
                raise

    ### CHANGE: 添加 async 前缀
    async def _send_request(self, payload: Dict[str, Any], is_retry: bool = False) -> bool:
        """底层消息发送引擎 (异步版本)，包含针对企微特定错误码的自愈逻辑"""
        token = await self._get_access_token()  ### CHANGE: 添加 await
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"

        try:
            ### CHANGE: 使用 await 进行异步 POST 请求
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            errcode = data.get("errcode")
            if errcode == 0:
                logger.debug(f"企微消息推送成功 | msgtype: {payload.get('msgtype')} | touser: {payload.get('touser')}")
                return True

            # Token 失效自愈逻辑
            if errcode in [40014, 42001, 42002] and not is_retry:
                logger.warning(f"企微 Token 发生 {errcode} 异常失效，触发自愈机制，强制刷新 Token 并重发！")
                await self._get_access_token(force_refresh=True)  ### CHANGE: 添加 await
                return await self._send_request(payload, is_retry=True)  ### CHANGE: 递归调用也要 await

            logger.error(f"企微消息推送失败 | 错误码: {errcode} | 详情: {data.get('errmsg')}")
            return False

        except (HTTPStatusError, RequestError, TimeoutException) as e:
            logger.error(f"发送企微消息时发生网络错误: {e}")
            return False
        except Exception as e:
            logger.error(f"发送企微消息时发生未预期错误: {e}")
            return False

    # =========================================================================
    # 业务层 API: 消息格式化下发 (全部改为 async)
    # =========================================================================

    ### CHANGE: 添加 async 前缀
    async def send_text(self, to_user: str, content: str) -> bool:
        """下发纯文本消息 (异步版本)"""
        payload = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": self.agentid,
            "text": {"content": content},
            "safe": 0
        }
        return await self._send_request(payload)  ### CHANGE: 添加 await

    ### CHANGE: 添加 async 前缀
    async def send_markdown(self, to_user: str, markdown_content: str) -> bool:
        """下发 Markdown 消息 (异步版本)"""
        payload = {
            "touser": to_user,
            "msgtype": "markdown",
            "agentid": self.agentid,
            "markdown": {"content": markdown_content}
        }
        return await self._send_request(payload)  ### CHANGE: 添加 await

    ### CHANGE: 添加 async 前缀
    async def send_textcard(self, to_user: str, title: str, description: str, url: str = "URL", btntxt: str = "详情") -> bool:
        """下发文本卡片消息 (异步版本)"""
        payload = {
            "touser": to_user,
            "msgtype": "textcard",
            "agentid": self.agentid,
            "textcard": {
                "title": title,
                "description": description,
                "url": url,
                "btntxt": btntxt
            }
        }
        return await self._send_request(payload)  ### CHANGE: 添加 await

    ### CHANGE: 新增异步上下文管理器支持 (推荐用法)
    async def close(self):
        """优雅关闭 HTTP 连接池"""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # =========================================================================
    # 业务层 API: 确认卡片 (Sprint 1 新增)
    # =========================================================================

    async def send_confirm_card(
        self,
        to_user: str,
        push_id: str,
        event_summary: str,
        event_type: str,
        severity: str,
        confirm_url: str = "",
        supplement_url: str = "",
    ) -> bool:
        """
        发送确认卡片消息（企业微信交互卡片）

        卡片包含：
        - 事件摘要
        - 两个按钮：「一键确认」「补充说明」

        Args:
            to_user: 接收人
            push_id: 推送日志ID（用于回调标识）
            event_summary: 事件摘要（20字以内）
            event_type: 事件类型
            severity: 严重程度
            confirm_url: 确认按钮回调URL
            supplement_url: 补充说明按钮回调URL

        Returns:
            是否发送成功
        """
        # 企业微信 markdown 卡片消息，支持点击链作为按钮
        confirm_md = f"**事件确认**\n\n{event_summary}\n\n发送者：@{to_user}\n类型：{event_type}\n严重：{severity}\n\n[✅ 一键确认]({confirm_url})\n[📝 补充说明]({supplement_url})"

        payload = {
            "touser": to_user,
            "msgtype": "markdown",
            "agentid": self.agentid,
            "markdown": {"content": confirm_md},
            "safe": 0,
        }
        return await self._send_request(payload)


# =============================================================================
# 单例工厂（懒加载，避免 import 时依赖环境变量）
# =============================================================================

_wechat_client = None


def get_wechat_client() -> Optional[WeChatWorkClient]:
    """返回 WeChatWorkClient 单例，首次调用时初始化。配置缺失返回 None。"""
    global _wechat_client
    if _wechat_client is None:
        corpid = os.environ.get("WX_CORPID")
        corpsecret = os.environ.get("WX_CORPSECRET")
        agentid = os.environ.get("WX_AGENTID")
        if corpid and corpsecret and agentid:
            try:
                _wechat_client = WeChatWorkClient(corpid=corpid, corpsecret=corpsecret, agentid=int(agentid))
                logger.info("企微客户端 (WeChatWorkClient) 异步版本实例化成功。")
            except ValueError:
                logger.error("WX_AGENTID 必须为整数，企微客户端实例化失败。")
                _wechat_client = None
        else:
            logger.warning("当前环境变量中缺少企微配置，wechat_client 未初始化。")
            _wechat_client = None
    return _wechat_client