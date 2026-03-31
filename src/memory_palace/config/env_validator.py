"""
env_validator.py · 环境变量验证器 (Fail-Fast)
================================================================
功能：
1. 启动前验证必需的环境变量
2. 支持必填/可选/条件必填配置
3. 敏感信息脱敏日志
4. 自定义验证规则
5. 与 ConfigManager 集成
"""

import os
import re
from typing import Any, Callable, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger


# ==============================================================================
# 验证类型
# ==============================================================================

class ValidationLevel(str, Enum):
    """验证级别"""
    ERROR = "error"      # 缺失直接退出
    WARNING = "warning"  # 缺失仅警告
    INFO = "info"       # 仅记录


class ValidationResult:
    """验证结果"""

    def __init__(self):
        self.passed: List[str] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_pass(self, key: str):
        self.passed.append(key)

    def add_warning(self, key: str, message: str):
        self.warnings.append(f"{key}: {message}")

    def add_error(self, key: str, message: str):
        self.errors.append(f"{key}: {message}")

    def raise_if_invalid(self):
        """如有错误则抛出异常"""
        if self.errors:
            error_msg = "\n".join(self.errors)
            raise EnvironmentError(
                f"❌ 环境变量验证失败，请检查以下配置:\n{error_msg}"
            )

    def log_summary(self):
        """输出验证摘要"""
        logger.info(f"📋 环境变量验证完成 | 通过: {len(self.passed)} | 警告: {len(self.warnings)} | 错误: {len(self.errors)}")
        if self.warnings:
            for w in self.warnings:
                logger.warning(f"  ⚠️ {w}")
        if self.errors:
            for e in self.errors:
                logger.error(f"  ❌ {e}")


# ==============================================================================
# 验证规则
# ==============================================================================

@dataclass
class EnvRule:
    """环境变量验证规则"""
    name: str
    env_key: str
    description: str
    level: ValidationLevel = ValidationLevel.ERROR
    default: Any = None
    required: bool = True
    validator: Optional[Callable[[str], bool]] = None
    error_message: Optional[str] = None
    transform: Optional[Callable[[str], Any]] = None  # 值转换器


# ==============================================================================
# 内置验证器
# ==============================================================================

class Validators:
    """内置验证器集合"""

    @staticmethod
    def is_url(value: str) -> bool:
        """验证 URL 格式"""
        pattern = r"^https?://[\w\-\.]+(:\d+)?(/.*)?$"
        return bool(re.match(pattern, value))

    @staticmethod
    def is_port(value: str) -> bool:
        """验证端口号"""
        try:
            port = int(value)
            return 1 <= port <= 65535
        except ValueError:
            return False

    @staticmethod
    def is_path(value: str) -> bool:
        """验证路径格式"""
        return bool(value and not value.strip() == "")

    @staticmethod
    def is_model_name(value: str) -> bool:
        """验证模型名称"""
        valid_models = [
            "gpt-4", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo",
            "claude-3-opus", "claude-3-sonnet", "claude-3-haiku",
            "gemini-pro", "gemini-ultra"
        ]
        return value in valid_models or value.startswith("gpt-") or value.startswith("claude-")

    @staticmethod
    def is_aes_key(value: str) -> bool:
        """验证 AES 密钥 (43位)"""
        return len(value) == 43

    @staticmethod
    def is_token(value: str) -> bool:
        """验证 Token 格式"""
        return len(value) >= 10

    @staticmethod
    def is_log_level(value: str) -> bool:
        """验证日志级别"""
        return value.upper() in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


# ==============================================================================
# 环境变量验证器
# ==============================================================================

class EnvValidator:
    """
    环境变量验证器

    用法：
        validator = EnvValidator()

        # 添加规则
        validator.add_rule(EnvRule(
            name="OpenAI API Key",
            env_key="OPENAI_API_KEY",
            description="OpenAI API 密钥",
            validator=lambda v: len(v) > 10
        ))

        # 执行验证
        result = validator.validate()
        result.raise_if_invalid()
    """

    def __init__(self):
        self.rules: List[EnvRule] = []
        self._setup_default_rules()

    def _setup_default_rules(self):
        """设置默认验证规则"""
        # 基础配置
        self.add_rule(EnvRule(
            name="运行环境",
            env_key="APP_ENV",
            description="应用环境",
            level=ValidationLevel.INFO,
            required=False,
            default="dev",
            validator=lambda v: v in ["dev", "test", "prod"]
        ))

        # LLM 配置
        self.add_rule(EnvRule(
            name="OpenAI API Key",
            env_key="OPENAI_API_KEY",
            description="OpenAI API 密钥 (生产必需)",
            level=ValidationLevel.ERROR,
            validator=Validators.is_token,
            error_message="请设置有效的 OPENAI_API_KEY"
        ))

        self.add_rule(EnvRule(
            name="LLM Base URL",
            env_key="LLM_BASE_URL",
            description="LLM API 地址 (可选，自定义中转时需要)",
            level=ValidationLevel.WARNING,
            required=False,
            default="https://api.openai.com/v1",
            validator=Validators.is_url
        ))

        # 企微配置
        self.add_rule(EnvRule(
            name="企微 Corp ID",
            env_key="WECHAT_CORP_ID",
            description="企业微信 Corp ID",
            level=ValidationLevel.ERROR,
            validator=lambda v: len(v) > 5
        ))

        self.add_rule(EnvRule(
            name="企微应用密钥",
            env_key="WECHAT_CORP_SECRET",
            description="企业微信应用密钥",
            level=ValidationLevel.ERROR,
            validator=Validators.is_token
        ))

        self.add_rule(EnvRule(
            name="企微回调 Token",
            env_key="WECHAT_TOKEN",
            description="企业微信回调 Token",
            level=ValidationLevel.ERROR,
            validator=Validators.is_token
        ))

        self.add_rule(EnvRule(
            name="企微加密密钥",
            env_key="WECHAT_ENCODING_AES_KEY",
            description="企业微信加密 AES Key",
            level=ValidationLevel.ERROR,
            validator=Validators.is_aes_key,
            error_message="AES Key 必须是 43 位字符"
        ))

        # 数据库配置 (可选，有默认值)
        self.add_rule(EnvRule(
            name="SQLite 路径",
            env_key="SQLITE_PATH",
            description="SQLite 数据库路径",
            level=ValidationLevel.INFO,
            required=False,
            default="data/memory.db"
        ))

        # 监控配置 (可选)
        self.add_rule(EnvRule(
            name="Prometheus 密码",
            env_key="PROMETHEUS_PASSWORD",
            description="Prometheus 认证密码",
            level=ValidationLevel.WARNING,
            required=False
        ))

        # Grafana 配置
        self.add_rule(EnvRule(
            name="Grafana 密码",
            env_key="GRAFANA_ADMIN_PASSWORD",
            description="Grafana 管理员密码",
            level=ValidationLevel.WARNING,
            required=False,
            default="admin123"
        ))

    def add_rule(self, rule: EnvRule):
        """添加验证规则"""
        self.rules.append(rule)

    def remove_rule(self, env_key: str):
        """移除验证规则"""
        self.rules = [r for r in self.rules if r.env_key != env_key]

    def validate(self) -> ValidationResult:
        """执行验证"""
        result = ValidationResult()

        for rule in self.rules:
            value = os.environ.get(rule.env_key)
            env_key = rule.env_key

            # 检查是否存在
            if value is None:
                if rule.required or rule.level == ValidationLevel.ERROR:
                    if rule.default is not None:
                        # 使用默认值
                        os.environ[env_key] = str(rule.default)
                        result.add_warning(
                            env_key,
                            f"未设置，使用默认值: {self._mask_value(env_key, rule.default)}"
                        )
                    else:
                        result.add_error(
                            env_key,
                            rule.error_message or f"环境变量 {env_key} 未设置"
                        )
                else:
                    result.add_info(
                        env_key,
                        f"未设置，可选配置"
                    ) if hasattr(result, 'add_info') else None
                continue

            # 执行自定义验证
            if rule.validator and not rule.validator(value):
                result.add_error(
                    env_key,
                    rule.error_message or f"环境变量 {env_key} 验证失败"
                )
                continue

            # 值转换
            if rule.transform:
                try:
                    os.environ[env_key] = str(rule.transform(value))
                except Exception as e:
                    result.add_error(env_key, f"值转换失败: {e}")
                    continue

            result.add_pass(env_key)

        return result

    def _mask_value(self, key: str, value: Any) -> str:
        """脱敏值显示"""
        key_lower = key.lower()
        sensitive_keywords = ["key", "secret", "password", "token", "aes"]

        if any(kw in key_lower for kw in sensitive_keywords):
            if isinstance(value, str) and len(value) > 8:
                return value[:4] + "****" + value[-4:]
            return "****"
        return str(value)

    def validate_and_raise(self):
        """验证并如有错误则抛出异常"""
        result = self.validate()
        result.log_summary()
        result.raise_if_invalid()


# ==============================================================================
# 便捷函数
# ==============================================================================

_validator: Optional[EnvValidator] = None


def get_validator() -> EnvValidator:
    """获取验证器单例"""
    global _validator
    if _validator is None:
        _validator = EnvValidator()
    return _validator


def validate_env() -> ValidationResult:
    """快捷验证函数"""
    validator = get_validator()
    return validator.validate()


def validate_env_strict():
    """严格验证，失败则退出"""
    validator = get_validator()
    validator.validate_and_raise()


# ==============================================================================
# 启动时自动调用
# ==============================================================================

def _auto_validate():
    """自动验证 (可由 main.py 调用)"""
    app_env = os.environ.get("APP_ENV", "dev")

    # 仅在非 dev 环境或显式启用时验证
    if app_env != "dev" or os.environ.get("FORCE_ENV_VALIDATION") == "1":
        logger.info(f"🔍 正在验证环境变量 (环境: {app_env})...")
        validate_env_strict()
    else:
        logger.debug("⏭️ 跳过环境变量验证 (dev 模式)")


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    "ValidationLevel",
    "ValidationResult",
    "EnvRule",
    "Validators",
    "EnvValidator",
    "get_validator",
    "validate_env",
    "validate_env_strict",
    "_auto_validate",
]

    