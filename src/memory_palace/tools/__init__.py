"""Tool adapters with lazy imports to keep optional runtimes isolated."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "WXBizMsgCrypt": ("wechat_crypto", "WXBizMsgCrypt"),
    "MockWeChatCrypto": ("wechat_crypto", "MockWeChatCrypto"),
    "WeChatCryptoError": ("wechat_crypto", "WeChatCryptoError"),
    "create_wechat_crypto": ("wechat_crypto", "create_wechat_crypto"),
    "LLMClient": ("llm_wrapper", "LLMClient"),
    "LLMResponse": ("llm_wrapper", "LLMResponse"),
    "llm_client": ("llm_wrapper", "llm_client"),
    "CircuitBreaker": ("circuit_breaker", "CircuitBreaker"),
    "CircuitBreakerOpen": ("circuit_breaker", "CircuitBreakerOpen"),
    "EmbeddingClient": ("embedding_client", "EmbeddingClient"),
    "get_embedding_client": ("embedding_client", "get_embedding_client"),
    "WeChatClient": ("wechat_client", "WeChatWorkClient"),
    "send_alert": ("sms_client", "send_alert"),
    "send_sms": ("sms_client", "send_sms"),
    "send_voice_call": ("sms_client", "send_voice_call"),
    "setup_logger": ("logger_config", "setup_logging"),
    "get_now": ("time_utils", "get_now"),
    "parse_to_datetime": ("time_utils", "parse_to_datetime"),
    "calculate_elapsed_minutes": ("time_utils", "calculate_elapsed_minutes"),
    "format_for_log": ("time_utils", "format_for_log"),
    "is_business_hours": ("time_utils", "is_business_hours"),
    "get_relative_time_desc": ("time_utils", "get_relative_time_desc"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in {"db_manager", "DatabaseManager"}:
        module = import_module(".db_client", __name__)
        return getattr(module, name)
    if name in _EXPORTS:
        module_name, attribute_name = _EXPORTS[name]
        return getattr(import_module(f".{module_name}", __name__), attribute_name)
    if name == "tool_executor":
        return import_module(".tool_executor", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
