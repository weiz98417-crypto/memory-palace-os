"""
工具集成层 (Atomic Tools Layer) - __init__.py
=============================================

统一暴露系统底层的原子能力，包括大模型调用、企微通信、短信告警、数据库连接等。
采用单例模式或依赖注入进行导出，确保全局资源池的高效利用。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

# 导入顺序建议：从无副作用的基础工具到依赖外部 IO 的客户端
from .time_utils import get_current_time, calculate_elapsed_minutes
from .llm_wrapper import llm_client
from .circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState

# WeChat crypto — 延迟导入，因为依赖 cryptography 库
try:
    from .wechat_crypto import WeChatCrypto
except ImportError:
    WeChatCrypto = None

# 由于 db_client, wechat_client, sms_client 强依赖于环境变量（如 Secret, DB_URI）
# 建议在实际使用处再进行 import，或者在这里暴露出工厂方法，而不是直接实例化单例。

__all__ = [
    # 时间工具
    "get_current_time",
    "calculate_elapsed_minutes",
    # LLM 客户端
    "llm_client",
    # 熔断器
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    # WeChat 加密
    "WeChatCrypto",
]