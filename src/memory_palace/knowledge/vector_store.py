"""PostgreSQL pgvector knowledge index backed by local bge-m3 embeddings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from loguru import logger

from ..tools.embedding_client import EMBEDDING_DIMENSION, build_embedding_backend


@dataclass(frozen=True)
class _IndexDescriptor:
    name: str


def _vector_literal(values: list[float]) -> str:
    if len(values) != EMBEDDING_DIMENSION:
        raise ValueError(
            f"bge-m3 vector dimension must be {EMBEDDING_DIMENSION}, got {len(values)}"
        )
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"


class PalaceVectorStore:
    """Small synchronous interface over the only production vector backend."""

    backend_mode = "postgresql_pgvector"
    model_name = "BAAI/bge-m3"
    model_version = "local-bge-m3-1024-v1"
    dimension = EMBEDDING_DIMENSION

    def __init__(
        self,
        *,
        embedding_function: Any = None,
        connection_factory: Optional[Callable[[], Any]] = None,
        dsn: Optional[str] = None,
    ) -> None:
        self._dsn = dsn or os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/memory_palace"
        )
        self._connection_factory = connection_factory or self._default_connection
        self.emb_fn = embedding_function or build_embedding_backend()
        self.collection = _IndexDescriptor(
            os.environ.get("PGVECTOR_INDEX_NAME", "knowledge_vectors_bge_m3_v1")
        )

    def _default_connection(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for the pgvector backend") from exc
        return psycopg.connect(self._dsn)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        backend = self.emb_fn
        if hasattr(backend, "embed_batch_sync"):
            vectors = backend.embed_batch_sync(texts)
        elif callable(backend):
            vectors = backend(texts)
        else:
            raise RuntimeError("embedding adapter does not provide a callable interface")
        if len(vectors) != len(texts):
            raise RuntimeError("embedding adapter returned an unexpected vector count")
        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSION:
                raise RuntimeError(
                    f"embedding adapter returned {len(vector)} dimensions; expected {EMBEDDING_DIMENSION}"
                )
        return vectors

    def health(self) -> dict[str, Any]:
        try:
            model_runtime = (
                self.emb_fn.probe()
                if hasattr(self.emb_fn, "probe")
                else {"status": "READY", "device": "custom", "dimension": EMBEDDING_DIMENSION}
            )
            with self._connection_factory() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                    )
                    extension = cursor.fetchone()
                    cursor.execute(
                        """
                        SELECT dimension, status FROM vector_index_versions
                        WHERE index_name = %s
                        """,
                        (self.collection.name,),
                    )
                    index = cursor.fetchone()
            if not extension or not index or int(index[0]) != EMBEDDING_DIMENSION:
                raise RuntimeError("pgvector schema or 1024-dimensional index is not ready")
            return {
                "status": "healthy",
                "backend": self.backend_mode,
                "extension_version": str(extension[0]),
                "index_name": self.collection.name,
                "model": self.model_name,
                "dimension": EMBEDDING_DIMENSION,
                "index_status": str(index[1]),
                "device": getattr(self.emb_fn, "device", "custom"),
                "model_runtime": model_runtime,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "backend": self.backend_mode,
                "index_name": self.collection.name,
                "model": self.model_name,
                "dimension": EMBEDDING_DIMENSION,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    def upsert_experience(
        self,
        content: str,
        metadata: dict[str, Any],
        doc_id: str,
        *,
        strict: bool = False,
    ) -> bool:
        venue_id = str(metadata.get("venue_id") or "").strip()
        if not venue_id:
            raise ValueError("venue_id is required for tenant-scoped vector writes")
        try:
            vector = _vector_literal(self._embed([content])[0])
            source_type = str(
                metadata.get("source_type") or metadata.get("asset_type") or "KNOWLEDGE"
            ).upper()
            source_id = str(
                metadata.get("source_id")
                or metadata.get("sop_id")
                or metadata.get("card_id")
                or metadata.get("event_id")
                or doc_id
            )
            source_version = str(metadata.get("version") or "1")
            with self._connection_factory() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO knowledge_vectors (
                            doc_id, venue_id, index_name, source_type, source_id,
                            source_version, content, metadata_json, model_name,
                            model_version, dimension, embedding, index_status,
                            indexed_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                            %s, %s::vector, 'READY', NOW(), NOW()
                        )
                        ON CONFLICT (doc_id) DO UPDATE SET
                            venue_id = EXCLUDED.venue_id,
                            index_name = EXCLUDED.index_name,
                            source_type = EXCLUDED.source_type,
                            source_id = EXCLUDED.source_id,
                            source_version = EXCLUDED.source_version,
                            content = EXCLUDED.content,
                            metadata_json = EXCLUDED.metadata_json,
                            model_name = EXCLUDED.model_name,
                            model_version = EXCLUDED.model_version,
                            dimension = EXCLUDED.dimension,
                            embedding = EXCLUDED.embedding,
                            index_status = 'READY',
                            error_message = NULL,
                            indexed_at = NOW(),
                            updated_at = NOW()
                        """,
                        (
                            doc_id,
                            venue_id,
                            self.collection.name,
                            source_type,
                            source_id,
                            source_version,
                            content,
                            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                            self.model_name,
                            self.model_version,
                            EMBEDDING_DIMENSION,
                            vector,
                        ),
                    )
            return True
        except Exception as exc:
            logger.error("pgvector upsert failed for {}: {}", doc_id, exc)
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
        source_types: Optional[list[str]] = None,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        if not venue_id or not venue_id.strip():
            raise ValueError("venue_id is required for tenant-scoped vector retrieval")
        normalized_types = (
            [str(item).upper() for item in source_types if str(item).strip()]
            if source_types
            else None
        )
        try:
            vector = _vector_literal(self._embed([text])[0])
            with self._connection_factory() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT doc_id, content, metadata_json,
                               1 - (embedding <=> %s::vector) AS similarity
                        FROM knowledge_vectors
                        WHERE venue_id = %s AND index_name = %s
                          AND index_status = 'READY' AND dimension = %s
                          AND (%s::text[] IS NULL OR source_type = ANY(%s::text[]))
                          AND 1 - (embedding <=> %s::vector) >= %s
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (
                            vector,
                            venue_id,
                            self.collection.name,
                            EMBEDDING_DIMENSION,
                            normalized_types,
                            normalized_types,
                            vector,
                            float(threshold),
                            vector,
                            max(1, int(top_k)),
                        ),
                    )
                    rows = cursor.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "content": str(row[1]),
                    "metadata": row[2] if isinstance(row[2], dict) else json.loads(row[2]),
                    "score": round(float(row[3]), 6),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("pgvector query failed: {}", exc)
            if strict:
                raise
            return []

    def delete_experience(self, doc_id: str, *, strict: bool = False) -> bool:
        try:
            with self._connection_factory() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM knowledge_vectors WHERE doc_id = %s", (doc_id,))
                    deleted = cursor.rowcount
            if strict and deleted != 1:
                raise RuntimeError(f"vector document not found: {doc_id}")
            return True
        except Exception:
            if strict:
                raise
            return False

    def verify_documents(self, doc_ids: list[str]) -> dict[str, Any]:
        """Return migration-safe index evidence without exposing database internals."""
        normalized_ids = list(dict.fromkeys(str(doc_id) for doc_id in doc_ids if str(doc_id)))
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                if normalized_ids:
                    cursor.execute(
                        """
                        SELECT COUNT(*), MIN(dimension), MAX(dimension)
                        FROM knowledge_vectors
                        WHERE index_name = %s AND doc_id = ANY(%s)
                        """,
                        (self.collection.name, normalized_ids),
                    )
                    count, min_dimension, max_dimension = cursor.fetchone()
                else:
                    count, min_dimension, max_dimension = 0, None, None
                cursor.execute(
                    """
                    SELECT model_name, model_version, dimension, status
                    FROM vector_index_versions WHERE index_name = %s
                    """,
                    (self.collection.name,),
                )
                version = cursor.fetchone()
        return {
            "document_count": int(count),
            "min_dimension": int(min_dimension) if min_dimension is not None else None,
            "max_dimension": int(max_dimension) if max_dimension is not None else None,
            "index_name": self.collection.name,
            "model_name": str(version[0]) if version else None,
            "model_version": str(version[1]) if version else None,
            "dimension": int(version[2]) if version else None,
            "status": str(version[3]) if version else None,
        }

    def close(self) -> None:
        return None


_vector_client: Optional[PalaceVectorStore] = None


def get_vector_client() -> Optional[PalaceVectorStore]:
    global _vector_client
    if _vector_client is None:
        try:
            _vector_client = PalaceVectorStore()
        except Exception as exc:
            if os.environ.get("APP_ENV", "dev").lower() in {"prod", "production"}:
                raise
            logger.warning("pgvector initialization failed: {}", exc)
            return None
    return _vector_client


def close_vector_client() -> None:
    global _vector_client
    client, _vector_client = _vector_client, None
    if client is not None:
        client.close()
