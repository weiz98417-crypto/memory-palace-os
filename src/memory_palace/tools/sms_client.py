"""
紧急通讯组件 (Emergency SMS/Voice Client)

核心特性：
1. 异步非阻塞发送：使用 ThreadPoolExecutor，防止发短信的网络 I/O 阻塞大模型或核心调度器的状态机流转。
2. 短信防轰炸限流 (Rate Limiting)：内存级本地缓存，限制同一手机号 1 分钟内只能接收 1 条相同级别的告警。
3. 语音强呼叫 (Voice TTS)：针对 P0 级事件，不仅发短信，还支持拨打语音电话 (TTS)，确保半夜能叫醒值班经理。
4. 抽象化云厂商 API：当前 Mock 阿里云/腾讯云的 SDK 结构，生产环境只需替换核心发送代码即可。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import time
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
import threading


class EmergencyNotifier:
    """紧急通讯网关（短信 + 语音电话）"""

    def __init__(self):
        # 实际生产中应从环境变量加载云厂商的 AK/SK
        self.access_key = os.environ.get("CLOUD_ACCESS_KEY", "dummy_ak")
        self.secret_key = os.environ.get("CLOUD_SECRET_KEY", "dummy_sk")
        self.sign_name = os.environ.get("SMS_SIGN_NAME", "记忆宫殿景区防线")

        # 1. 独立线程池：不阻塞主业务流程，分配 5 个线程专门处理短信任物
        self.executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="SMSWorker")

        # 2. 防轰炸限流记录 (Phone -> Timestamp)
        self._send_records: Dict[str, float] = {}
        self._rate_lock = threading.Lock()
        
        # 同一手机号的防刷冷却时间（秒）
        self.cooldown_seconds = 60 

    def _check_rate_limit(self, phone: str) -> bool:
        """检查是否触发了防轰炸限流策略"""
        with self._rate_lock:
            now = time.time()
            last_send_time = self._send_records.get(phone, 0.0)
            if now - last_send_time < self.cooldown_seconds:
                return False
            self._send_records[phone] = now
            return True

    def _sync_send_sms(self, phone: str, template_code: str, params: Dict[str, Any]) -> bool:
        """底层同步发短信逻辑（此处为云厂商 SDK 占位）"""
        try:
            logger.debug(f"[云通讯网关] 正在向 {phone} 发送短信 | 模板: {template_code} | 参数: {params}")
            
            # TODO: 此处替换为真实的 Aliyun/Tencent SDK 调用
            # client = Client(config)
            # request = SendSmsRequest(phone_numbers=phone, sign_name=self.sign_name...)
            # response = client.send_sms(request)
            
            # 模拟网络延迟
            time.sleep(0.5) 
            
            logger.success(f"[云通讯网关] 🚨 告警短信已成功投递至: {phone}")
            return True
        except Exception as e:
            logger.error(f"[云通讯网关] 短信发送彻底失败: {e}")
            return False

    def _sync_send_voice_call(self, phone: str, tts_code: str, params: Dict[str, Any]) -> bool:
        """底层同步打语音电话逻辑（此处为云厂商 SDK 占位）"""
        try:
            logger.warning(f"[云通讯网关] 正在对 {phone} 发起高危语音呼叫 (TTS) | 模板: {tts_code}")
            
            # 模拟网络延迟
            time.sleep(1.0)
            
            logger.success(f"[云通讯网关] 🚨 语音电话已成功接通: {phone}")
            return True
        except Exception as e:
            logger.error(f"[云通讯网关] 语音电话呼叫失败: {e}")
            return False

    # =========================================================================
    # 业务层 API: 异步非阻塞调用
    # =========================================================================

    def send_p1_alert(self, phones: List[str], event_desc: str, location: str) -> None:
        """下发 P1 级重大事件告警（仅短信）"""
        for phone in phones:
            if not self._check_rate_limit(phone):
                logger.warning(f"[限流拦截] {phone} 在 {self.cooldown_seconds}s 内已接收过短信，本次拦截。")
                continue
            
            # 提交给线程池异步执行，立刻 return，不卡死大模型流程
            self.executor.submit(
                self._sync_send_sms, 
                phone, 
                "SMS_P1_TEMPLATE", 
                {"event": event_desc, "loc": location}
            )

    def send_p0_critical(self, phones: List[str], event_desc: str) -> None:
        """下发 P0 级致命事件告警（短信 + 连环语音呼叫）"""
        for phone in phones:
            if not self._check_rate_limit(phone):
                logger.warning(f"[限流拦截] {phone} 处于冷却期，不再重复拨打 P0 语音。")
                continue
            
            # 双管齐下：发短信的同时打电话
            self.executor.submit(
                self._sync_send_sms, 
                phone, 
                "SMS_P0_CRITICAL", 
                {"event": event_desc}
            )
            self.executor.submit(
                self._sync_send_voice_call, 
                phone, 
                "TTS_P0_WAKEUP", 
                {"event": event_desc}
            )


# 导出全局单例
sms_client = EmergencyNotifier()


# ─────────────────────────────────────────────────────────────────────────────
# 便捷告警函数
# ─────────────────────────────────────────────────────────────────────────────

def send_sms(phone: str, event_desc: str, severity: str = "P2") -> None:
    """发送短信告警"""
    if severity == "P0":
        sms_client.send_p0_critical([phone], event_desc)
    else:
        sms_client.send_p1_alert([phone], event_desc, "")


def send_voice_call(phone: str, event_desc: str) -> None:
    """发起语音呼叫"""
    sms_client.executor.submit(
        sms_client._sync_send_voice_call,
        phone,
        "TTS_P0_WAKEUP",
        {"event": event_desc}
    )


def send_alert(message: str, level: str = "P2", phones: Optional[list[str]] = None) -> None:
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
        logger.warning(f"[send_alert] 未配置告警手机号，仅记录日志: {message}")
        return

    if level == "P0":
        sms_client.send_p0_critical(target_phones, message)
    elif level == "P1":
        sms_client.send_p1_alert(target_phones, message, "")
    else:
        logger.info(f"[send_alert:{level}] {message}")