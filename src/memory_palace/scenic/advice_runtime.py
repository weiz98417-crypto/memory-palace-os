"""Explicit selection and validation of the advice execution runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass

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


__all__ = ["AdviceRuntimeConfig"]
