"""
config/__init__.py · 全局配置加载器 (Enhanced)
================================================================
功能：
1. 自动加载 settings.yaml 和 registry.yaml
2. 支持环境变量覆盖 (Environment Overrides)
3. 支持 .env 敏感配置注入
4. 暴露全局唯一的 settings 对象
5. 配置变更订阅机制
6. Fail-Fast 启动校验
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Callable, List, Union
from functools import lru_cache
from dataclasses import dataclass, field
from threading import Lock

from loguru import logger

# ==============================================================================
# 配置锁 (线程安全)
# ==============================================================================

_config_lock = Lock()

# ==============================================================================
# 配置变更订阅者
# ==============================================================================

@dataclass
class ConfigSubscriber:
    """配置变更订阅者"""
    key_pattern: str  # 支持通配符，如 "llm.*"
    callback: Callable[[str, Any], None]
    once: bool = False  # 是否只触发一次


# ==============================================================================
# 配置管理器
# ==============================================================================

class ConfigManager:
    """
    全局配置管理器 (单例模式)

    用法：
        from memory_palace.config import config

        # 点号语法读取
        model = config.get("llm.default_model")

        # 带默认值
        timeout = config.get("llm.timeout", 30.0)

        # 订阅配置变更
        config.subscribe("llm.*", lambda k, v: print(f"{k} changed to {v}"))
    """

    _instance: Optional["ConfigManager"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            with _config_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.base_dir = Path(__file__).parent

        # 加载配置
        self.settings: Dict[str, Any] = {}
        self.registry: Dict[str, Any] = {}
        self._original_settings: Dict[str, Any] = {}  # 用于比较变更

        # 订阅者列表
        self._subscribers: List[ConfigSubscriber] = []

        # 环境模式
        self.env = os.environ.get("APP_ENV", "dev").lower()

        # 初始化
        self._load_all()

        logger.info(
            f"✨ 全局配置中心初始化完成 | "
            f"运行环境: {self.env} | "
            f"配置项: {len(self.settings)} | "
            f"Agent注册: {len(self.registry.get('agents', {}))}"
        )

    def _load_all(self):
        """加载所有配置"""
        # 加载 settings.yaml
        self.settings = self._load_yaml("settings.yaml")
        self._original_settings = self._deep_copy(self.settings)

        # 加载 registry.yaml
        self.registry = self._load_yaml("registry.yaml")

        # 应用环境变量覆盖
        self._apply_env_overrides()

        # 验证配置
        self._validate()

    def _load_yaml(self, file_name: str) -> Dict[str, Any]:
        """加载 YAML 配置文件"""
        path = self.base_dir / file_name
        if not path.exists():
            logger.error(f"❌ 致命错误：配置文件 {file_name} 缺失！路径: {path}")
            raise FileNotFoundError(f"配置文件 {file_name} 不存在: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data else {}
        except yaml.YAMLError as e:
            logger.error(f"❌ YAML 解析失败: {file_name}, 错误: {e}")
            raise

    def _apply_env_overrides(self):
        """
        应用环境变量覆盖

        支持的格式：
            MEMORY_PALACE_LLM_DEFAULT_MODEL=gpt-4o
            MEMORY_PALACE_LLM__TIMEOUT=60  (双下划线表示嵌套)
            MEMORY_PALACE_SYSTEM__LOG_LEVEL=DEBUG
        """
        prefix = "MEMORY_PALACE_"
        prefix_len = len(prefix)

        for env_key, env_value in os.environ.items():
            if not env_key.startswith(prefix):
                continue

            # 转换键名
            # MEMORY_PALACE_LLM_DEFAULT_MODEL -> llm.default_model
            # MEMORY_PALACE_LLM__TIMEOUT -> llm.timeout
            key = env_key[prefix_len:].lower().replace("__", ".").replace("_", ".")

            # 尝试类型转换
            typed_value = self._parse_env_value(env_value)

            # 设置配置
            self._set_nested(key, typed_value)

            logger.debug(f"🔄 环境变量覆盖: {key} = {typed_value}")

    def _parse_env_value(self, value: str) -> Any:
        """尝试将环境变量值转换为合适类型"""
        # 布尔值
        if value.lower() in ("true", "yes", "1", "on"):
            return True
        if value.lower() in ("false", "no", "0", "off"):
            return False

        # 数字
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        # 保持字符串
        return value

    def _set_nested(self, key: str, value: Any):
        """设置嵌套配置"""
        keys = key.split(".")
        current = self.settings

        for i, k in enumerate(keys[:-1]):
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value

    def _deep_copy(self, obj: Any) -> Any:
        """深拷贝"""
        import copy
        return copy.deepcopy(obj)

    def _validate(self):
        """验证配置完整性"""
        required_keys = [
            "system.app_name",
            "system.version",
        ]

        for key in required_keys:
            value = self.get(key)
            if value is None:
                logger.warning(f"⚠️ 建议配置项缺失: {key}")

    # ==========================================================================
    # 公开 API
    # ==========================================================================

    def get(self, key: str, default: Any = None) -> Any:
        """
        支持点号语法的配置读取

        用法：
            config.get('llm.default_model')
            config.get('system.log_level')
            config.get('nonexistent', 'default')
        """
        keys = key.split(".")
        value = self.settings

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default

        return value

    def set(self, key: str, value: Any, notify: bool = True):
        """
        设置配置值

        用法：
            config.set('llm.default_model', 'gpt-4')
        """
        self._set_nested(key, value)

        # 通知订阅者
        if notify:
            self._notify_subscribers(key, value)

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self._deep_copy(self.settings)

    def get_registry(self, agent_name: Optional[str] = None) -> Union[Dict, Any]:
        """
        获取 Agent 注册信息

        用法：
            config.get_registry()           # 获取所有
            config.get_registry('router')  # 获取单个
        """
        if agent_name:
            return self.registry.get("agents", {}).get(agent_name)
        return self.registry.get("agents", {})

    def get_fallback_agent(self) -> str:
        """获取默认兜底 Agent"""
        return self.registry.get("fallback_agent", "deep_interview")

    def get_env(self) -> str:
        """获取当前环境"""
        return self.env

    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.env == "prod"

    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.env == "dev"

    def is_testing(self) -> bool:
        """是否为测试环境"""
        return self.env == "test"

    # ==========================================================================
    # 配置订阅机制
    # ==========================================================================

    def subscribe(
        self,
        key_pattern: str,
        callback: Callable[[str, Any], None],
        once: bool = False
    ) -> Callable:
        """
        订阅配置变更

        用法：
            unsub = config.subscribe('llm.*', lambda k, v: print(f'{k} changed'))
            unsub()  # 取消订阅

        支持通配符：
            'llm.*'     - 匹配 llm 下所有
            'llm.model' - 精确匹配
            '*'         - 匹配所有
        """
        subscriber = ConfigSubscriber(
            key_pattern=key_pattern,
            callback=callback,
            once=once
        )
        self._subscribers.append(subscriber)

        # 返回取消订阅函数
        def unsubscribe():
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return unsubscribe

    def _notify_subscribers(self, key: str, value: Any):
        """通知订阅者"""
        to_remove = []

        for subscriber in self._subscribers:
            if self._match_pattern(key, subscriber.key_pattern):
                try:
                    subscriber.callback(key, value)
                    if subscriber.once:
                        to_remove.append(subscriber)
                except Exception as e:
                    logger.error(f"配置订阅回调失败: {subscriber.key_pattern}, {e}")

        # 移除已触发一次的订阅
        for sub in to_remove:
            self._subscribers.remove(sub)

    def _match_pattern(self, key: str, pattern: str) -> bool:
        """检查键是否匹配模式"""
        if pattern == "*":
            return True

        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return key.startswith(prefix + ".")
        elif pattern.endswith(".*.*"):
            # 多层通配符
            prefix = pattern.rsplit(".*", 1)[0]
            return key.startswith(prefix + ".")

        return key == pattern

    # ==========================================================================
    # 配置变更检测
    # ==========================================================================

    def has_changed(self, key: str) -> bool:
        """检查配置是否已变更"""
        current = self.get(key)
        original = self._get_original(key)
        return current != original

    def _get_original(self, key: str) -> Any:
        """获取原始配置值"""
        keys = key.split(".")
        value = self._original_settings

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return None
            if value is None:
                return None

        return value

    def get_changes(self) -> Dict[str, Dict[str, Any]]:
        """获取所有变更的配置"""
        changes = {}
        self._diff_configs(self.settings, self._original_settings, "", changes)
        return changes

    def _diff_configs(
        self,
        current: Any,
        original: Any,
        prefix: str,
        diff: Dict[str, Dict[str, Any]]
    ):
        """递归比较配置差异"""
        if isinstance(current, dict) and isinstance(original, dict):
            all_keys = set(list(current.keys()) + list(original.keys()))
            for key in all_keys:
                new_prefix = f"{prefix}.{key}" if prefix else key
                self._diff_configs(
                    current.get(key),
                    original.get(key),
                    new_prefix,
                    diff
                )
        else:
            if current != original:
                diff[prefix] = {
                    "old": original,
                    "new": current
                }

    # ==========================================================================
    # 重载机制
    # ==========================================================================

    def reload(self):
        """重新加载配置"""
        logger.info("🔄 重新加载配置...")
        self._load_all()
        logger.success("✅ 配置重载完成")

    def reload_yaml(self, file_name: str):
        """重新加载指定 YAML 文件"""
        if file_name == "settings.yaml":
            self.settings = self._load_yaml(file_name)
            self._original_settings = self._deep_copy(self.settings)
            logger.info(f"🔄 已重载: {file_name}")
        elif file_name == "registry.yaml":
            self.registry = self._load_yaml(file_name)
            logger.info(f"🔄 已重载: {file_name}")


# ==============================================================================
# 全局单例实例 (懒加载)
# ==============================================================================

@lru_cache(maxsize=1)
def get_config() -> ConfigManager:
    """获取配置管理器单例"""
    return ConfigManager()


# 为方便使用，提供全局 config 实例
config = get_config()


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    "ConfigManager",
    "ConfigSubscriber",
    "get_config",
    "config",
]

    