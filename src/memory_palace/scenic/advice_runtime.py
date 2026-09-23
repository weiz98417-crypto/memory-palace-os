"""Explicit selection and validation of the advice execution runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from ..config.secrets import read_secret


@dataclass(frozen=True)
class AdviceRuntimeConfig:
    mode: str

    @classmethod
    def from_env(cls) -> "AdviceRuntimeConfig":
        mode = os.environ.get("ADVICE_EXECUTION_MODE", "redis").strip().lower()
        if mode not in {"redis", "hatchet"}:
            raise RuntimeError("ADVICE_EXECUTION_MODE 必须为 redis 或 hatchet")
        if mode == "hatchet":
            try:
                token = read_secret("HATCHET_CLIENT_TOKEN") or ""
            except RuntimeError as exc:
                raise RuntimeError("Hatchet token 文件不可读") from exc
            if not token.strip():
                raise RuntimeError("Hatchet token 必须通过环境变量或可读非空文件提供")
        return cls(mode=mode)

    async def validate_dependencies(self) -> None:
        if self.mode != "hatchet":
            return
        health_url = os.environ.get("HATCHET_HEALTH_URL", "").strip()
        if not health_url:
            raise RuntimeError(
                "Hatchet 模式必须配置 HATCHET_HEALTH_URL，以验证 Hatchet 服务已就绪"
            )
        worker_ready_file = os.environ.get("HATCHET_WORKER_READY_FILE", "").strip()
        if not worker_ready_file:
            raise RuntimeError(
                "Hatchet 模式必须配置 HATCHET_WORKER_READY_FILE，以验证 worker 已就绪"
            )
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                response = await client.get(health_url)
        except Exception as exc:
            raise RuntimeError("Hatchet 服务不可达，无法进入 Hatchet 模式") from exc
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"Hatchet 服务健康检查失败（HTTP {response.status_code}）"
            )
        worker_ready = os.path.isfile(worker_ready_file) and os.path.getsize(worker_ready_file) > 0
        if not worker_ready:
            raise RuntimeError("Hatchet worker 尚未就绪，无法进入 Hatchet 模式")


__all__ = ["AdviceRuntimeConfig"]
