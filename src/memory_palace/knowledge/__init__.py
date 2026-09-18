"""
知识库与数据持久化层入口 (Knowledge Layer Entry) - __init__.py
=============================================================

统一管理关系型数据库与 PostgreSQL pgvector 向量索引的实例。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

from .db_client import db_client, db_manager
from .vector_store import get_vector_client

__all__ = [
    "db_client",
    "db_manager",
    "get_vector_client",
]
