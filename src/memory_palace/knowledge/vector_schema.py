"""Idempotent pgvector schema and startup contract checks."""

from __future__ import annotations

import os


INDEX_NAME = "knowledge_vectors_bge_m3_v1"
MODEL_NAME = "BAAI/bge-m3"
DIMENSION = 1024

# ADR-0020: the index version must name the runtime that actually produced the
# vectors. TEI is the production runtime; the local sentence-transformers path is
# only the rollback branch, selected when no TEI URL is configured.
TEI_MODEL_VERSION = "tei-bge-m3-1.9.4-1024-v1"
LOCAL_MODEL_VERSION = "local-bge-m3-1024-v1"


def _embedding_provider() -> str:
    return "TEI" if os.environ.get("SCENIC_TEI_EMBEDDING_URL", "").strip() else "LOCAL"


def _model_version() -> str:
    return TEI_MODEL_VERSION if _embedding_provider() == "TEI" else LOCAL_MODEL_VERSION


async def init_vector_schema(database) -> None:
    statements = (
        "CREATE EXTENSION IF NOT EXISTS vector",
        """
        CREATE TABLE IF NOT EXISTS vector_index_versions (
            index_name TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension = 1024),
            status TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            validated_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS knowledge_vectors (
            doc_id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            index_name TEXT NOT NULL REFERENCES vector_index_versions(index_name),
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_version TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension = 1024),
            embedding vector(1024) NOT NULL,
            index_status TEXT NOT NULL,
            error_message TEXT,
            indexed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (venue_id, index_name, source_type, source_id, source_version)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_knowledge_vectors_tenant_source
        ON knowledge_vectors (venue_id, index_name, source_type, source_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_knowledge_vectors_hnsw
        ON knowledge_vectors USING hnsw (embedding vector_cosine_ops)
        """,
    )
    for statement in statements:
        await database.execute(statement)
    await database.execute(
        """
        INSERT INTO vector_index_versions (
            index_name, provider, model_name, model_version, dimension, status, validated_at
        ) VALUES (?, ?, ?, ?, ?, 'READY', NOW())
        ON CONFLICT (index_name) DO UPDATE SET
            provider = EXCLUDED.provider,
            model_name = EXCLUDED.model_name,
            model_version = EXCLUDED.model_version,
            dimension = EXCLUDED.dimension,
            status = 'READY',
            validated_at = NOW()
        """,
        (INDEX_NAME, _embedding_provider(), MODEL_NAME, _model_version(), DIMENSION),
    )


async def verify_vector_schema(database) -> dict[str, object]:
    extension = await database.fetch_one(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    )
    index = await database.fetch_one(
        """
        SELECT index_name, model_name, model_version, dimension, status
        FROM vector_index_versions WHERE index_name = ?
        """,
        (INDEX_NAME,),
    )
    if not extension or not index:
        raise RuntimeError("pgvector extension or index version is missing")
    if int(index["dimension"]) != DIMENSION or index["status"] != "READY":
        raise RuntimeError("pgvector index contract is not ready")
    return {
        "backend": "postgresql_pgvector",
        "extension_version": extension["extversion"],
        **index,
    }
