"""Secrets management — centralized validation at startup."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def read_secret(name: str, default: str = "") -> str:
    """Read a secret from an environment variable or its Docker-style file."""
    value = os.environ.get(name)
    if value:
        return value

    file_path = os.environ.get(f"{name}_FILE")
    if not file_path:
        return default

    try:
        return Path(file_path).read_text(encoding="utf-8-sig").strip() or default
    except OSError as exc:
        raise RuntimeError(f"无法读取 {name}_FILE 指向的密钥文件") from exc


@dataclass(frozen=True)
class Secrets:
    DATABASE_URL: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    REDIS_URL: str = field(default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379"))
    LLM_PRIMARY_API_KEY: str = field(
        default_factory=lambda: read_secret("DEEPSEEK_API_KEY")
    )
    LLM_PRIMARY_BASE_URL: str = field(
        default_factory=lambda: os.environ.get("DEEPSEEK_BASE_URL", "") or "https://api.deepseek.com/v1"
    )
    LLM_FALLBACK_API_KEY: str = field(default_factory=lambda: os.environ.get("LLM_FALLBACK_API_KEY", ""))
    WECHAT_CORP_ID: str = field(default_factory=lambda: os.environ.get("WECHAT_CORP_ID", ""))
    WECHAT_CORP_SECRET: str = field(default_factory=lambda: os.environ.get("WECHAT_CORP_SECRET", ""))
    WECHAT_TOKEN: str = field(default_factory=lambda: os.environ.get("WECHAT_TOKEN", ""))
    WECHAT_ENCODING_AES_KEY: str = field(default_factory=lambda: os.environ.get("WECHAT_ENCODING_AES_KEY", ""))
    JWT_SECRET: str = field(default_factory=lambda: os.environ.get("MEMORY_PALACE_JWT_SECRET", ""))
    API_KEYS: str = field(default_factory=lambda: os.environ.get("MEMORY_PALACE_API_KEYS", ""))
    ADMIN_PASSWORD: str = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD", ""))

    def validate(self, demo_mode: bool = False) -> list[str]:
        """Return list of missing REQUIRED secrets. Empty list = all good."""
        if demo_mode:
            return []
        required = {
            "DATABASE_URL": self.DATABASE_URL,
            "LLM_PRIMARY_API_KEY": self.LLM_PRIMARY_API_KEY,
            "JWT_SECRET": self.JWT_SECRET,
            "ADMIN_PASSWORD": self.ADMIN_PASSWORD,
        }
        return [k for k, v in required.items() if not v]


secrets = Secrets()
