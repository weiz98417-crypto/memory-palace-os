"""
知识库与数据持久化层入口 (Knowledge Layer Entry)

统一管理关系型数据库 (SQLAlchemy) 与向量数据库 (ChromaDB) 的实例。
"""

from .db_client import db_manager, SOPDocument, IncidentLog
from .vector_store import get_vector_client

__all__ = [
    "db_manager",
    "SOPDocument",
    "IncidentLog",
    "get_vector_client"
]