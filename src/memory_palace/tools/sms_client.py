"""
紧急通讯组件 (Emergency SMS/Voice Client)

核心特性：
1. 异步非阻塞发送：使用 ThreadPoolExecutor，防止发短信的网络 I/O 阻塞大模型或核心调度器的状态机流转。
2. 短信防轰炸限流 (Rate Limiting)：内存级本地缓存，限制同一手机号 1 分钟内只能接收 1 条相同级别的告警。
3. 语音强呼叫 (Voice TTS)：针对 P0 级事件，不仅发短信，还支持拨打语音电话 (TTS)，确保半夜能叫醒值班经理。
4. 抽象化云厂商 API：只有注入真实供应商 Adapter 后才允许发送，未配置时明确禁用。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import os
import time
from typing import Any, Callable, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
import threading


class NotificationUnavailable(RuntimeError):
    code = "DISABLED_REQUIRES_CONFIG"

    def __init__(self, channel: str, missing: list[str]):
        self.channel = channel
        self.missing = missing
        super().__init__(f"{channel} notification is unavailable; missing: {', '.join(missing)}")


class EmergencyNotifier:
    """紧急通讯网关（短信 + 语音电话）"""

    def __init__(
        self,
        *,
        sms_sender: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None,
        voice_sender: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None,
    ):
        self.sms_provider = os.environ.get("SMS_PROVIDER", "").strip()
        self.sms_api_key = os.environ.get("SMS_API_KEY", "").strip()
        self.voice_provider = os.environ.get("VOICE_PROVIDER", "").strip()
        self.voice_api_key = os.environ.get("VOICE_API_KEY", "").strip()
        self.sign_name = os.environ.get("SMS_SIGN_NAME", "记忆宫殿景区防线")
        self._sms_sender = sms_sender
        self._voice_sender = voice_sender

        # 1. 独立线程池：不阻塞主业务流程，分配 5 个线程专门处理短信任物
        self.executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="SMSWorker")
        self._closed = False
        self._shutdown_lock = threading.Lock()

        # 2. 防轰炸限流记录 (Phone -> Timestamp)
        self._send_records: Dict[str, float] = {}
        self._rate_lock = threading.Lock()

        # 同一手机号的防刷冷却时间（秒）
        self.cooldown_seconds = 60

    def _require_channel(self, channel: str) -> None:
        if channel == "sms":
            missing = [] if self._sms_sender else ["SMS_PROVIDER_ADAPTER"]
        else:
            missing = [] if self._voice_sender else ["VOICE_PROVIDER_ADAPTER"]
        if missing:
            raise NotificationUnavailable(channel, missing)

    def _check_rate_limit(self, phone: str) -> bool:
        """检查是否触发了防轰炸限流策略"""
        with self._rate_lock:
            now = time.time()
            last_send_time = self._send_records.get(phone, 0.0)
            if now - last_send_time < self.cooldown_seconds:
                return False
            self._send_records[phone] = now
            return True

    def _sync_send_sms(self, phone: str, template_code: str, params: Dict[str, Any]) -> Any:
        """通过已注入的真实供应商 Adapter 发送短信。"""
        self._require_channel("sms")
        logger.debug(f"[云通讯网关] 正在向 {phone} 发送短信 | 模板: {template_code}")
        response = self._sms_sender(phone, template_code, params)
        if response is False or response is None:
            raise RuntimeError("SMS provider did not confirm delivery")
        logger.success(f"[云通讯网关] 短信供应商已确认投递: {phone}")
        return response

    def _sync_send_voice_call(self, phone: str, tts_code: str, params: Dict[str, Any]) -> Any:
        """通过已注入的真实供应商 Adapter 发起语音电话。"""
        self._require_channel("voice")
        logger.warning(f"[云通讯网关] 正在对 {phone} 发起高危语音呼叫 (TTS) | 模板: {tts_code}")
        response = self._voice_sender(phone, tts_code, params)
        if response is False or response is None:
            raise RuntimeError("Voice provider did not confirm delivery")
        logger.success(f"[云通讯网关] 语音供应商已确认呼叫: {phone}")
        return response

    # =========================================================================
    # 业务层 API: 异步非阻塞调用
    # =========================================================================

    def send_p1_alert(self, phones: List[str], event_desc: str, location: str) -> list:
        """下发 P1 级重大事件告警（仅短信）"""
        self._require_channel("sms")
        futures = []
        for phone in phones:
            if not self._check_rate_limit(phone):
                logger.warning(f"[限流拦截] {phone} 在 {self.cooldown_seconds}s 内已接收过短信，本次拦截。")
                continue

            futures.append(
                self.executor.submit(
                    self._sync_send_sms,
                    phone,
                    "SMS_P1_TEMPLATE",
                    {"event": event_desc, "loc": location},
                )
            )
        return futures

    def send_p0_critical(self, phones: List[str], event_desc: str) -> list:
        """下发 P0 级致命事件告警（短信 + 连环语音呼叫）"""
        self._require_channel("sms")
        self._require_channel("voice")
        futures = []
        for phone in phones:
            if not self._check_rate_limit(phone):
                logger.warning(f"[限流拦截] {phone} 处于冷却期，不再重复拨打 P0 语音。")
                continue

            futures.append(self.executor.submit(self._sync_send_sms, phone, "SMS_P0_CRITICAL", {"event": event_desc}))
            futures.append(
                self.executor.submit(self._sync_send_voice_call, phone, "TTS_P0_WAKEUP", {"event": event_desc})
            )
        return futures

    def close(self, wait: bool = True) -> None:
        """Stop worker threads so application and test processes can exit cleanly."""
        with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
            self.executor.shutdown(wait=wait, cancel_futures=True)

    def __enter__(self) -> "EmergencyNotifier":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


# 导出全局单例
sms_client = EmergencyNotifier()


# ─────────────────────────────────────────────────────────────────────────────
# 便捷告警函数
# ─────────────────────────────────────────────────────────────────────────────



def notification_channel_readiness(channel: str) -> dict[str, Any]:
    channel_name = channel.strip().lower()
    senders = {
        "sms": sms_client._sms_sender,
        "voice": sms_client._voice_sender,
    }
    if channel_name not in senders:
        return {
            "available": False,
            "channel": channel_name,
            "missing": ["NOTIFICATION_CHANNEL_UNSUPPORTED"],
        }
    adapter_name = f"{channel_name.upper()}_PROVIDER_ADAPTER"
    available = senders[channel_name] is not None
    return {
        "available": available,
        "channel": channel_name,
        "missing": [] if available else [adapter_name],
    }


def notification_action_readiness(tool_name: str, priority: str = "") -> dict[str, Any]:
    action_name = tool_name.strip().lower()
    required_channels = ["sms"]
    missing = []
    if action_name == "send_alert":
        if not any(phone.strip() for phone in os.environ.get("ALERT_PHONES", "").split(",")):
            missing.append("ALERT_PHONES")
        if priority.strip().lower() == "critical":
            required_channels.append("voice")
    elif action_name != "send_sms":
        return {
            "available": False,
            "channels": [],
            "missing": ["NOTIFICATION_ACTION_UNSUPPORTED"],
        }
    for channel in required_channels:
        missing.extend(notification_channel_readiness(channel)["missing"])
    return {
        "available": not missing,
        "channels": required_channels,
        "missing": sorted(set(missing)),
    }

async def _await_futures(futures: list) -> list[Any]:
    return await asyncio.gather(*(asyncio.wrap_future(future) for future in futures))


async def send_sms(phone: str, event_desc: str, severity: str = "P2") -> dict[str, Any]:
    """发送短信告警"""
    if severity == "P0":
        futures = sms_client.send_p0_critical([phone], event_desc)
        channels = ["sms", "voice"]
    else:
        futures = sms_client.send_p1_alert([phone], event_desc, "")
        channels = ["sms"]
    if not futures:
        return {"status": "RATE_LIMITED", "sent": False, "phone": phone, "channels": channels}
    await _await_futures(futures)
    return {"status": "DELIVERED", "sent": True, "phone": phone, "channels": channels}


async def send_voice_call(phone: str, event_desc: str) -> dict[str, Any]:
    """发起语音呼叫"""
    sms_client._require_channel("voice")
    future = sms_client.executor.submit(
        sms_client._sync_send_voice_call,
        phone,
        "TTS_P0_WAKEUP",
        {"event": event_desc},
    )
    await _await_futures([future])
    return {"status": "DELIVERED", "sent": True, "phone": phone, "channels": ["voice"]}


async def send_alert(message: str, level: str = "P2", phones: Optional[list[str]] = None) -> dict[str, Any]:
    """
    发送告警通知（便捷函数）

    Args:
        message: 告警消息
        level: 告警级别 (P0/P1/P2/P3/P4)
        phones: 指定接收人手机号列表（可选，默认用环境变量）
    """
    target_phones = phones or os.environ.get("ALERT_PHONES", "").split(",")
    target_phones = [p.strip() for p in target_phones if p.strip()]

    if not target_phones:
        raise NotificationUnavailable("alert", ["ALERT_PHONES"])

    severity = "P0" if level.upper() in {"P0", "CRITICAL"} else "P1"
    receipts = await asyncio.gather(*(send_sms(phone, message, severity) for phone in target_phones))
    return {
        "status": "DELIVERED" if all(receipt["sent"] for receipt in receipts) else "PARTIAL",
        "sent": all(receipt["sent"] for receipt in receipts),
        "level": level,
        "receipts": receipts,
    }
