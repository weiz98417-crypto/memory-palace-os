"""
REST API 层 (API Layer) - __init__.py
=====================================

提供 FastAPI 应用入口及 v1/v2 版本路由。

子包：
  - v1/  v1 版本 API
  - v2/  v2 版本 API（新增功能）

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

from .v1.router import router as v1_router
from .v2.router import router as v2_router

__all__ = ["v1_router", "v2_router"]
