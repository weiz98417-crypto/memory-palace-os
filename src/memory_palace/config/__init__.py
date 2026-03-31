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

# 直接从 init.py（模块文件）导入，Python 会查找同目录的 init.py
from .init import ConfigManager, ConfigSubscriber, get_config, config

__all__ = [
    "ConfigManager",
    "ConfigSubscriber",
    "get_config",
    "config",
]
