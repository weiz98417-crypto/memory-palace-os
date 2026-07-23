"""
配置管理包 (Config Package) - __init__.py
==========================================

本包提供全局配置管理，支持：
1. settings.yaml / registry.yaml 自动加载
2. 环境变量覆盖 (Environment Overrides)
3. 配置变更订阅机制
4. Fail-Fast 启动校验

用法：
    from memory_palace.config import config
    model = config.get("llm.default_model")

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

# 从 config_manager.py 导入核心配置类
from .config_manager import ConfigManager, ConfigSubscriber, get_config, config

__all__ = [
    "ConfigManager",
    "ConfigSubscriber",
    "get_config",
    "config",
]
