"""
app_settings.py · Pydantic 强类型配置 (可选增强层)
================================================================
功能：
1. 提供强类型的配置模型 (替代 dict 访问)
2. 自动从 ConfigManager 同步配置
3. 支持配置验证和默认值
4. IDE 自动补全支持

用法 (可选):
    from memory_palace.config.app_settings import settings

    # 强类型访问
    model = settings.llm.default_model
    timeout = settings.llm.timeout

注意: ConfigManager 仍然是最基础的配置层,
      此文件提供强类型访问的增强体验。
"""

import os
from typing import Dict, Any, Optional, List
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings
from loguru import logger

# 导入基础配置
from . import config


# ==============================================================================
# Pydantic 模型定义
# ==============================================================================

class SystemSettings(BaseModel):
    """系统配置"""
    app_name: str = Field(default="MemoryPalaceOS", description="应用名称")
    version: str = Field(default="1.0.0", description="版本号")
    timezone: str = Field(default="Asia/Shanghai", description="时区")
    log_level: str = Field(default="INFO", description="日志级别")
    data_dir: str = Field(default="./data", description="数据目录")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()


class LLMSettings(BaseModel):
    """LLM 配置"""
    default_model: str = Field(default="gpt-4o", description="默认模型")
    timeout: float = Field(default=30.0, ge=1.0, le=300.0, description="超时时间(秒)")
    max_retries: int = Field(default=3, ge=0, le=10, description="最大重试次数")
    base_url: str = Field(
        default="https://api.openai.com/v1",
        description="API 地址"
    )
    api_key: Optional[str] = Field(default=None, description="API Key (从环境变量读取)")

    @property
    def effective_api_key(self) -> str:
        """获取有效的 API Key"""
        if self.api_key:
            return self.api_key
        return os.environ.get("OPENAI_API_KEY", "")


class StorageSettings(BaseModel):
    """存储配置"""
    sqlite_path: str = Field(default="data/memory.db", description="SQLite 路径")
    vector_db_path: str = Field(default="data/vector_db", description="向量数据库路径")
    pool_size: int = Field(default=10, ge=1, le=100, description="连接池大小")
    max_overflow: int = Field(default=20, ge=0, le=100, description="最大溢出连接")

    @field_validator("sqlite_path", "vector_db_path")
    @classmethod
    def validate_paths(cls, v: str) -> str:
        if not v.startswith("/") and not v.startswith("./"):
            return f"./{v}"
        return v


class WeChatSettings(BaseModel):
    """企业微信配置"""
    callback_port: int = Field(default=8080, ge=1, le=65535, description="回调端口")
    token_refresh_margin: int = Field(
        default=200,
        ge=60,
        description="Token 续期提前时间(秒)"
    )

    # 从环境变量读取敏感信息
    corp_id: Optional[str] = Field(default=None, description="企业 ID")
    corp_secret: Optional[str] = Field(default=None, description="应用密钥")
    token: Optional[str] = Field(default=None, description="回调 Token")
    encoding_aes_key: Optional[str] = Field(default=None, description="加密密钥")

    @property
    def effective_corp_id(self) -> str:
        return self.corp_id or os.environ.get("WECHAT_CORP_ID", "")

    @property
    def effective_corp_secret(self) -> str:
        return self.corp_secret or os.environ.get("WECHAT_CORP_SECRET", "")

    @property
    def effective_token(self) -> str:
        return self.token or os.environ.get("WECHAT_TOKEN", "")

    @property
    def effective_encoding_aes_key(self) -> str:
        return self.encoding_aes_key or os.environ.get("WECHAT_ENCODING_AES_KEY", "")


class SLAPolicySettings(BaseModel):
    """SLA 策略配置"""
    p0_timeout_min: int = Field(default=3, ge=1, description="P0 超时(分钟)")
    p1_timeout_min: int = Field(default=10, ge=1, description="P1 超时(分钟)")
    p2_timeout_min: int = Field(default=30, ge=1, description="P2 超时(分钟)")
    auto_escalation: bool = Field(default=True, description="是否自动升级")


class QueueSettings(BaseModel):
    """消息队列配置"""
    max_size: int = Field(default=10000, ge=100, description="队列最大长度")
    retry_limit: int = Field(default=3, ge=0, description="消息重试次数")
    retry_delay_seconds: float = Field(default=1.0, ge=0.1, description="重试延迟")
    dead_letter_enabled: bool = Field(default=True, description="死信队列启用")


class MetricsSettings(BaseModel):
    """监控配置"""
    enabled: bool = Field(default=True, description="是否启用监控")
    port: int = Field(default=9090, ge=1, le=65535, description="Prometheus 端口")
    scrape_interval: int = Field(default=15, ge=5, description="采集间隔(秒)")


class SecuritySettings(BaseModel):
    """安全配置"""
    cors_enabled: bool = Field(default=True, description="CORS 启用")
    cors_origins: List[str] = Field(
        default=["*"],
        description="允许的源"
    )
    api_key_required: bool = Field(default=False, description="API Key 验证")
    rate_limit_enabled: bool = Field(default=True, description="限流启用")
    rate_limit_requests: int = Field(default=100, ge=1, description="每分钟请求数")


# ==============================================================================
# 根配置模型
# ==============================================================================

class AppSettings(BaseModel):
    """应用全局配置 (强类型)"""

    system: SystemSettings = Field(default_factory=SystemSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    wechat: WeChatSettings = Field(default_factory=WeChatSettings)
    sla_policy: SLAPolicySettings = Field(default_factory=SLAPolicySettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    metrics: MetricsSettings = Field(default_factory=MetricsSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    class Config:
        extra = "ignore"  # 忽略额外字段


# ==============================================================================
# 配置同步器
# ==============================================================================

class SettingsSync:
    """
    配置同步器 - 保持 Pydantic 模型与 ConfigManager 同步
    """

    def __init__(self):
        self._settings: Optional[AppSettings] = None

    def sync_from_config_manager(self) -> AppSettings:
        """从 ConfigManager 同步配置到 Pydantic 模型"""
        c = config

        self._settings = AppSettings(
            system=SystemSettings(
                app_name=c.get("system.app_name", "MemoryPalaceOS"),
                version=c.get("system.version", "1.0.0"),
                timezone=c.get("system.timezone", "Asia/Shanghai"),
                log_level=c.get("system.log_level", "INFO"),
                data_dir=c.get("system.data_dir", "./data"),
            ),
            llm=LLMSettings(
                default_model=c.get("llm.default_model", "gpt-4o"),
                timeout=c.get("llm.timeout", 30.0),
                max_retries=c.get("llm.max_retries", 3),
                base_url=c.get("llm.base_url", "https://api.openai.com/v1"),
                api_key=os.environ.get("OPENAI_API_KEY"),
            ),
            storage=StorageSettings(
                sqlite_path=c.get("storage.sqlite_path", "data/memory.db"),
                vector_db_path=c.get("storage.vector_db_path", "data/vector_db"),
                pool_size=c.get("storage.pool_size", 10),
                max_overflow=c.get("storage.max_overflow", 20),
            ),
            wechat=WeChatSettings(
                callback_port=c.get("wechat.callback_port", 8080),
                token_refresh_margin=c.get("wechat.token_refresh_margin", 200),
            ),
            sla_policy=SLAPolicySettings(
                p0_timeout_min=c.get("sla_policy.p0_timeout_min", 3),
                p1_timeout_min=c.get("sla_policy.p1_timeout_min", 10),
                p2_timeout_min=c.get("sla_policy.p2_timeout_min", 30),
                auto_escalation=c.get("sla_policy.auto_escalation", True),
            ),
            queue=QueueSettings(
                max_size=c.get("queue.max_size", 10000),
                retry_limit=c.get("queue.retry_limit", 3),
                retry_delay_seconds=c.get("queue.retry_delay_seconds", 1.0),
                dead_letter_enabled=c.get("queue.dead_letter_enabled", True),
            ),
            metrics=MetricsSettings(
                enabled=c.get("metrics.enabled", True),
                port=c.get("metrics.port", 9090),
                scrape_interval=c.get("metrics.scrape_interval", 15),
            ),
            security=SecuritySettings(
                cors_enabled=c.get("security.cors_enabled", True),
                cors_origins=c.get("security.cors_origins", ["*"]),
                api_key_required=c.get("security.api_key_required", False),
                rate_limit_enabled=c.get("security.rate_limit_enabled", True),
                rate_limit_requests=c.get("security.rate_limit_requests", 100),
            ),
        )

        return self._settings

    def get_settings(self) -> AppSettings:
        """获取配置(带缓存)"""
        if self._settings is None:
            return self.sync_from_config_manager()
        return self._settings

    def invalidate(self):
        """使缓存失效"""
        self._settings = None


# ==============================================================================
# 全局实例
# ==============================================================================

_settings_sync = SettingsSync()


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """获取强类型配置 (带缓存)"""
    return _settings_sync.sync_from_config_manager()


# 便捷访问
settings = get_settings()


def reload_settings() -> AppSettings:
    """重新加载配置（清除缓存后重新读取）"""
    get_settings.cache_clear()
    _settings_sync.invalidate()
    new_settings = get_settings()
    logger.info("应用配置已重新加载")
    return new_settings


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    # 模型
    "AppSettings",
    "SystemSettings",
    "LLMSettings",
    "StorageSettings",
    "WeChatSettings",
    "SLAPolicySettings",
    "QueueSettings",
    "MetricsSettings",
    "SecuritySettings",

    # 工具
    "SettingsSync",
    "get_settings",
    "settings",
    "reload_settings",
]

    