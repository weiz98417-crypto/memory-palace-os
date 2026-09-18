"""
知识库与数据持久化层入口 (Knowledge Layer Entry)

统一管理 PostgreSQL 业务事实与 pgvector 向量索引的实例。
"""

from .db_client import db_manager, SOPDocument, IncidentLog
from .vector_store import get_vector_client

__all__ = [
    "db_manager",
    "SOPDocument",
    "IncidentLog",
    "get_vector_client"
]
