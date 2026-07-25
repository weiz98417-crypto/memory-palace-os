"""Secrets management — centralized validation at startup."""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Secrets:
    DATABASE_URL: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    REDIS_URL: str = field(default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379"))
    LLM_PRIMARY_API_KEY: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    LLM_PRIMARY_BASE_URL: str = field(default_factory=lambda: os.environ.get("OPENAI_BASE_URL", ""))
    LLM_FALLBACK_API_KEY: str = field(default_factory=lambda: os.environ.get("LLM_FALLBACK_API_KEY", ""))
    WECHAT_CORP_ID: str = field(default_factory=lambda: os.environ.get("WECHAT_CORP_ID", ""))
    WECHAT_CORP_SECRET: str = field(default_factory=lambda: os.environ.get("WECHAT_CORP_SECRET", ""))
    WECHAT_TOKEN: str = field(default_factory=lambda: os.environ.get("WECHAT_TOKEN", ""))
    WECHAT_ENCODING_AES_KEY: str = field(default_factory=lambda: os.environ.get("WECHAT_ENCODING_AES_KEY", ""))
    JWT_SECRET: str = field(default_factory=lambda: os.environ.get("MEMORY_PALACE_JWT_SECRET", ""))
    API_KEYS: str = field(default_factory=lambda: os.environ.get("MEMORY_PALACE_API_KEYS", ""))

    def validate(self, demo_mode: bool = False) -> list[str]:
        """Return list of missing REQUIRED secrets. Empty list = all good."""
        if demo_mode:
            return []
        required = {
            "DATABASE_URL": self.DATABASE_URL,
            "LLM_PRIMARY_API_KEY": self.LLM_PRIMARY_API_KEY,
        }
        return [k for k, v in required.items() if not v]


secrets = Secrets()
