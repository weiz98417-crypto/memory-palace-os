"""Stable API error contract for the enterprise client."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .audit import request_trace_id


def api_error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    action: str,
    *,
    retryable: bool = False,
    details: dict | None = None,
) -> HTTPException:
    detail = {
        "code": code,
        "message": message,
        "trace_id": request_trace_id(request),
        "retryable": retryable,
        "action": action,
    }
    if details:
        detail.update(details)
    return HTTPException(
        status_code=status_code,
        detail=detail,
    )


def _error_payload(request: Request, status_code: int, detail) -> dict:
    if isinstance(detail, dict) and detail.get("code"):
        payload = dict(detail)
        payload.setdefault("trace_id", request_trace_id(request))
        payload.setdefault("retryable", status_code >= 500 or status_code == 429)
        payload.setdefault("action", "请根据提示修正后重试。")
        return payload

    if status_code >= 500:
        message = "服务器处理请求时发生错误。"
        action = "稍后重试；如持续失败，请使用 Trace ID 联系管理员。"
    else:
        message = str(detail) if detail else "请求未能完成。"
        action = "检查请求和当前权限后重试。"
    return {
        "code": f"HTTP_{status_code}",
        "message": message,
        "trace_id": request_trace_id(request),
        "retryable": status_code >= 500 or status_code == 429,
        "action": action,
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        first_error = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first_error.get("loc", ()) if part != "body")
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "REQUEST_VALIDATION_FAILED",
                    "message": f"请求参数不符合要求{f'：{location}' if location else ''}。",
                    "trace_id": request_trace_id(request),
                    "retryable": False,
                    "action": "检查必填项、格式和长度后重试。",
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": _error_payload(request, exc.status_code, exc.detail)},
            headers=exc.headers,
        )
