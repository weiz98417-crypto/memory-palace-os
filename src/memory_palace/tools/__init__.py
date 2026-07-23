"""
tools/__init__.py - 工具集成层导出
"""
from .wechat_crypto import WXBizMsgCrypt, MockWeChatCrypto, WeChatCryptoError, create_wechat_crypto
from .llm_wrapper import LLMClient, LLMResponse, llm_client
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from .embedding_client import EmbeddingClient, get_embedding_client
from .wechat_client import WeChatWorkClient as WeChatClient
from .sms_client import send_alert, send_sms, send_voice_call
from .logger_config import setup_logging as setup_logger
from .time_utils import get_now, parse_to_datetime, calculate_elapsed_minutes, format_for_log, is_business_hours, get_relative_time_desc
from .db_client import db_manager, DatabaseManager

__all__ = [
    # 加解密
    "WXBizMsgCrypt",
    "MockWeChatCrypto",
    "WeChatCryptoError",
    "create_wechat_crypto",
    # LLM
    "LLMClient",
    "LLMResponse",
    "llm_client",
    # 熔断器
    "CircuitBreaker",
    "CircuitBreakerOpen",
    # Embedding
    "EmbeddingClient",
    "get_embedding_client",
    # 企微客户端
    "WeChatClient",
    # 短信告警
    "send_alert",
    "send_sms",
    "send_voice_call",
    # 日志
    "setup_logger",
    # 时间工具
    "get_now",
    "parse_to_datetime",
    "calculate_elapsed_minutes",
    "format_for_log",
    "is_business_hours",
    "get_relative_time_desc",
    # 数据库
    "db_manager",
    "DatabaseManager",
]
