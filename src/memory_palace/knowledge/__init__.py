"""
知识库与数据持久化层入口 (Knowledge Layer Entry) - __init__.py
=============================================================

统一管理关系型数据库 (aiosqlite) 与向量数据库 (ChromaDB) 的实例。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

from .db_client import db_client, db_manager
from .vector_store import vector_client

__all__ = [
    "db_client",
    "db_manager",
    "vector_client",
]
