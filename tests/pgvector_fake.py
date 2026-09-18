from __future__ import annotations

import hashlib
import json
import math

from src.memory_palace.knowledge.vector_store import PalaceVectorStore


class DeterministicEmbeddingBackend:
    device = "test"

    def embed_batch_sync(self, texts):
        vectors = []
        for text in texts:
            digest = hashlib.sha256(str(text).encode("utf-8")).digest()
            vector = [float(digest[index % len(digest)] + 1) for index in range(1024)]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


class FakePgVectorDatabase:
    def __init__(self):
        self.documents = {}

    def connect(self):
        return _Connection(self)


class _Connection:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _Cursor(self.database)


class _Cursor:
    def __init__(self, database):
        self.database = database
        self.rows = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, parameters=()):
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("INSERT INTO KNOWLEDGE_VECTORS"):
            (
                doc_id,
                venue_id,
                index_name,
                source_type,
                source_id,
                source_version,
                content,
                metadata_json,
                model_name,
                model_version,
                dimension,
                vector,
            ) = parameters
            self.database.documents[str(doc_id)] = {
                "doc_id": str(doc_id),
                "venue_id": venue_id,
                "index_name": index_name,
                "source_type": source_type,
                "source_id": source_id,
                "source_version": source_version,
                "content": content,
                "metadata": json.loads(metadata_json),
                "model_name": model_name,
                "model_version": model_version,
                "dimension": dimension,
                "vector": json.loads(vector),
            }
            self.rowcount = 1
            self.rows = []
            return
        if "SELECT DOC_ID, CONTENT, METADATA_JSON" in normalized:
            query_vector = json.loads(parameters[0])
            venue_id = parameters[1]
            index_name = parameters[2]
            source_types = parameters[4]
            threshold = float(parameters[7])
            limit = int(parameters[9])
            allowed_types = (
                {str(item).upper() for item in source_types} if source_types else None
            )
            matches = []
            for document in self.database.documents.values():
                if document["venue_id"] != venue_id or document["index_name"] != index_name:
                    continue
                if allowed_types and str(document["source_type"]).upper() not in allowed_types:
                    continue
                similarity = _cosine(query_vector, document["vector"])
                if similarity >= threshold:
                    matches.append(
                        (
                            document["doc_id"],
                            document["content"],
                            document["metadata"],
                            similarity,
                        )
                    )
            self.rows = sorted(matches, key=lambda row: row[3], reverse=True)[:limit]
            return
        if normalized.startswith("DELETE FROM KNOWLEDGE_VECTORS"):
            self.rowcount = int(self.database.documents.pop(str(parameters[0]), None) is not None)
            self.rows = []
            return
        if "SELECT EXTVERSION FROM PG_EXTENSION" in normalized:
            self.rows = [("0.8.1",)]
            return
        if "SELECT DIMENSION, STATUS FROM VECTOR_INDEX_VERSIONS" in normalized:
            self.rows = [(1024, "READY")]
            return
        if "SELECT MODEL_NAME, MODEL_VERSION, DIMENSION, STATUS" in normalized:
            self.rows = [("BAAI/bge-m3", "local-bge-m3-1024-v1", 1024, "READY")]
            return
        if "SELECT COUNT(*), MIN(DIMENSION), MAX(DIMENSION)" in normalized:
            index_name, doc_ids = parameters
            dimensions = [
                document["dimension"]
                for document in self.database.documents.values()
                if document["index_name"] == index_name and document["doc_id"] in doc_ids
            ]
            self.rows = [
                (
                    len(dimensions),
                    min(dimensions) if dimensions else None,
                    max(dimensions) if dimensions else None,
                )
            ]
            return
        raise AssertionError(f"Unexpected pgvector SQL: {normalized}")

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


def _cosine(left, right):
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def build_fake_pgvector_store():
    database = FakePgVectorDatabase()
    store = PalaceVectorStore(
        embedding_function=DeterministicEmbeddingBackend(),
        connection_factory=database.connect,
        dsn="postgresql://test",
    )
    return store, database
