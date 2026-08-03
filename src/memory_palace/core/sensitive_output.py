"""Public-output sanitization for operational and administrative views."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal


ErrorContext = Literal["model", "queue", "operation"]

_SECRET_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "credentials",
    "password",
    "passwd",
    "secret",
    "set_cookie",
    "token",
}
_PROMPT_KEYS = {
    "messages",
    "prompt",
    "prompt_text",
    "raw_prompt",
    "system_prompt",
    "user_prompt",
}
_SAFE_PROMPT_KEYS = {"prompt_finalize", "prompt_tokens", "prompt_token_count"}
_PRIVATE_PATH_KEYS = {
    "file_path",
    "filesystem_path",
    "local_path",
    "object_path",
    "storage_key",
    "storage_path",
}
_RAW_ERROR_KEYS = {
    "error",
    "error_message",
    "exception",
    "exception_message",
    "execution_error",
    "failure_reason",
    "last_error",
    "raw_error",
    "traceback",
}

_INLINE_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:Authorization|Proxy-Authorization)\s*:\s*[^;\r\n]+",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:Cookie|Set-Cookie)\s*:\s*[^\r\n]+", re.IGNORECASE),
    re.compile(
        r"\b(?:prompt|system[_-]?prompt|user[_-]?prompt)\s*[:=]\s*[^;\r\n]+",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{6,}=*", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_-]?key|authorization|cookie|set-cookie|password|passwd|"
        r"secret|access[_-]?token|refresh[_-]?token|token|system[_-]?prompt|"
        r"user[_-]?prompt|prompt)\s*[:=]\s*[^\s;,\]\}\)]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    ),
)
_PRIVATE_PATH_PATTERN = re.compile(
    r"(?:(?:[A-Za-z]:[\\/]|/(?:app|data|home|opt|srv|tmp|var)/|"
    r"(?:az|azure|file|gs|s3)://)"
    r"[^\s;,\]\}\)\"']*?(?:attachments|objects|private|uploads)|"
    r"(?<![A-Za-z0-9_.\\/-])(?:attachments|objects|private|uploads)[\\/])"
    r"[^\s;,\]\}\)\"']*",
    re.IGNORECASE,
)


def sanitize_public_value(value: Any) -> Any:
    """Return JSON-safe public data with sensitive keys and values removed."""

    return _sanitize(value)


def public_record(record: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Build a sanitized field-whitelist DTO from a persistence record."""

    selected = {field: record[field] for field in fields if field in record}
    sanitized = sanitize_public_value(selected)
    return sanitized if isinstance(sanitized, dict) else {}


def public_error_message(
    error: Any,
    *,
    context: ErrorContext = "operation",
) -> str | None:
    """Map an untrusted exception to a stable actionable Chinese summary."""

    if error in (None, ""):
        return None
    lowered = str(error).lower()

    if any(
        marker in lowered
        for marker in (
            "401",
            "403",
            "api key",
            "api_key",
            "authentication",
            "authorization",
            "credential",
            "forbidden",
            "permission denied",
            "unauthorized",
            "凭据",
            "密钥",
            "鉴权",
        )
    ):
        return {
            "model": "模型服务鉴权失败，请检查模型凭据后重试。",
            "queue": "任务处理鉴权失败，请检查依赖服务凭据后重试。",
            "operation": "操作鉴权失败，请检查依赖服务凭据后重试。",
        }[context]
    if "429" in lowered or any(
        marker in lowered
        for marker in ("rate limit", "too many requests", "过于频繁", "限流")
    ):
        return {
            "model": "模型服务请求过于频繁，请稍后重试。",
            "queue": "任务处理请求过于频繁，请稍后重试。",
            "operation": "操作请求过于频繁，请稍后重试。",
        }[context]
    if any(marker in lowered for marker in ("timeout", "timed out", "超时")):
        return {
            "model": "模型服务响应超时，请稍后重试。",
            "queue": "任务处理超时，请稍后重试。",
            "operation": "操作超时，请稍后重试。",
        }[context]
    if any(
        marker in lowered
        for marker in (
            "connection",
            "connecterror",
            "connectionerror",
            "dns",
            "network",
            "service unavailable",
            "连接",
            "网络",
        )
    ):
        return {
            "model": "模型服务连接失败，请检查依赖服务状态后重试。",
            "queue": "任务处理依赖连接失败，请检查服务状态后重试。",
            "operation": "依赖服务连接失败，请检查服务状态后重试。",
        }[context]
    if any(
        marker in lowered
        for marker in ("decode", "invalid json", "parse", "response format", "格式")
    ):
        return {
            "model": "模型服务返回格式异常，请重试；持续失败请联系管理员。",
            "queue": "任务载荷格式异常，请修复数据后重试。",
            "operation": "返回数据格式异常，请重试；持续失败请联系管理员。",
        }[context]
    if any(marker in lowered for marker in ("cancel", "cancelled", "canceled", "取消")):
        return "任务已取消，请重新发起。"
    if any(marker in lowered for marker in ("not found", "不存在")):
        return "目标记录不存在，请刷新后重试。"
    if any(marker in lowered for marker in ("already", "conflict", "状态已变化")):
        return "当前状态已变化，请刷新后重试。"
    return {
        "model": "模型服务处理失败，请携带 Trace ID 联系管理员后重试。",
        "queue": "任务处理失败，请携带 Trace ID 排查后重试。",
        "operation": "操作失败，请携带 Trace ID 联系管理员后重试。",
    }[context]


def _sanitize(value: Any, *, key: str = "") -> Any:
    normalized_key = _normalized_key(key)
    if _is_sensitive_key(normalized_key):
        return _Omit
    if _is_raw_error_key(normalized_key):
        return public_error_message(value)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for item_key, item_value in value.items():
            public_value = _sanitize(item_value, key=str(item_key))
            if public_value is not _Omit:
                sanitized[str(item_key)] = public_value
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            public_value
            for item in value
            if (public_value := _sanitize(item)) is not _Omit
        ]
    if not isinstance(value, str):
        return value
    sanitized_text = value
    for pattern in _INLINE_SECRET_PATTERNS:
        sanitized_text = pattern.sub("[已隐藏]", sanitized_text)
    return _PRIVATE_PATH_PATTERN.sub("[已隐藏]", sanitized_text)


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    if not key:
        return False
    if key in _SECRET_KEYS or key in _PRIVATE_PATH_KEYS:
        return True
    if key in _PROMPT_KEYS:
        return True
    if key not in _SAFE_PROMPT_KEYS and (key.startswith("prompt_") or key.endswith("_prompt")):
        return True
    return any(
        key.endswith(suffix)
        for suffix in (
            "_api_key",
            "_authorization",
            "_cookie",
            "_credentials",
            "_password",
            "_secret",
            "_token",
        )
    )


def _is_raw_error_key(key: str) -> bool:
    return key in _RAW_ERROR_KEYS or key.endswith(
        ("_error", "_exception", "_stack_trace", "_stacktrace", "_traceback")
    )


class _OmitType:
    pass


_Omit = _OmitType()
