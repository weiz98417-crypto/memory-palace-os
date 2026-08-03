"""
向量检索接口 (ChromaDB Vector Store)

核心特性：
1. Embedding 抽象：统一封装文本转向量过程。
2. 余弦相似度检索：精准定位历史经验片段。
3. 持久化防护：支持本地 SQLite 存储向量数据，保障重启不丢失。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional
from loguru import logger


class PalaceVectorStore:
    def __init__(self, *, embedding_function=None):
        app_env = os.environ.get("APP_ENV", "dev").lower()
        chroma_host = os.environ.get("CHROMA_HOST", "").strip()
        self.emb_fn = embedding_function or embedding_functions.DefaultEmbeddingFunction()

        if chroma_host:
            chroma_port = int(os.environ.get("CHROMA_PORT", "8000"))
            chroma_ssl = os.environ.get("CHROMA_SSL", "false").lower() == "true"
            self._client = chromadb.HttpClient(host=chroma_host, port=chroma_port, ssl=chroma_ssl)
            self.backend_mode = "remote_http"
            self.db_path = None
        else:
            if app_env in {"prod", "production"}:
                raise RuntimeError("正式环境必须配置 CHROMA_HOST，禁止回退到本地向量库")
            self.db_path = os.environ.get(
                "CHROMA_PERSIST_DIR",
                os.environ.get("VECTOR_DB_PATH", "data/vector_db"),
            )
            self._client = chromadb.PersistentClient(path=self.db_path)
            self.backend_mode = "local_persistent"

        self.collection = self._client.get_or_create_collection(
            name=os.environ.get("CHROMA_COLLECTION", "memory_palace_vdb"),
            embedding_function=self.emb_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("向量知识库初始化完成，后端: {}", self.backend_mode)

    def health(self) -> Dict[str, Any]:
        try:
            heartbeat = self._client.heartbeat()
            return {
                "status": "healthy",
                "backend": self.backend_mode,
                "heartbeat": heartbeat,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "backend": self.backend_mode,
                "error_type": type(exc).__name__,
            }

    def upsert_experience(
        self,
        content: str,
        metadata: Dict[str, Any],
        doc_id: str,
        *,
        strict: bool = False,
    ) -> bool:
        """插入或更新一条经验碎片"""
        try:
            self.collection.upsert(documents=[content], metadatas=[metadata], ids=[doc_id])
            logger.debug(f"[VectorStore] 数据上云: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"[VectorStore] Upsert 失败: {e}")
            if strict:
                raise
            return False

    def query_experience(
        self,
        text: str,
        top_k: int = 3,
        threshold: float = 0.75,
        *,
        venue_id: str,
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        语义检索逻辑：带相似度阈值过滤，防止召回毫无相关的噪音。
        """
        if not venue_id or not venue_id.strip():
            raise ValueError("venue_id is required for tenant-scoped vector retrieval")
        try:
            query_args: Dict[str, Any] = {
                "query_texts": [text],
                "n_results": top_k,
                "include": ["documents", "metadatas", "distances"],
            }
            query_args["where"] = {"venue_id": venue_id}
            results = self.collection.query(**query_args)

            clean_results = []
            if not results or not results["documents"]:
                return []

            for i in range(len(results["documents"][0])):
                # Chroma 的 cosine distance = 1 - similarity
                similarity = 1 - results["distances"][0][i]

                # 工业级过滤：低于阈值的通通丢弃，宁可不给建议也不乱给建议
                if similarity >= threshold:
                    clean_results.append(
                        {
                            "id": results.get("ids", [[]])[0][i],
                            "content": results["documents"][0][i],
                            "metadata": results["metadatas"][0][i],
                            "score": round(similarity, 3),
                        }
                    )

            return clean_results
        except Exception as e:
            logger.error(f"[VectorStore] 检索过程中断: {e}")
            if strict:
                raise
            return []

    def delete_experience(self, doc_id: str, *, strict: bool = False) -> bool:
        """删除一条向量记录。"""
        try:
            self.collection.delete(ids=[doc_id])
            logger.debug(f"[VectorStore] 数据已删除: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"[VectorStore] 删除失败: {e}")
            if strict:
                raise
            return False

    def close(self) -> None:
        """Release Chroma's background runtime when the store is no longer used."""
        client = getattr(self, "_client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()
        self._client = None


# 单例工厂（懒加载，避免 import 时触发 ChromaDB/OpenAI 初始化）
_vector_client = None


def get_vector_client() -> Optional[PalaceVectorStore]:
    """返回 PalaceVectorStore 单例，首次调用时初始化。初始化失败返回 None。"""
    global _vector_client
    if _vector_client is None:
        try:
            _vector_client = PalaceVectorStore()
        except Exception as e:
            if os.environ.get("APP_ENV", "dev").lower() in {"prod", "production"}:
                raise
            logger.warning(f"[VectorStore] 初始化失败（将以降级模式运行）: {e}")
            _vector_client = None
    return _vector_client


def close_vector_client() -> None:
    """Close and clear the lazily-created process-wide vector client."""
    global _vector_client
    client, _vector_client = _vector_client, None
    if client is not None:
        client.close()
