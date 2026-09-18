"""Embedding adapters for the pgvector index.

Two interchangeable runtimes sit behind `EmbeddingBackend`:

- `LocalEmbeddingBackend`: local sentence-transformers, kept only as the explicit
  rollback path (it needs the opt-in torch extra).
- `TEIEmbeddingBackend`: bge-m3 served by text-embeddings-inference over HTTP. This is
  the production runtime, which is why the app image no longer ships torch (ADR-0020).

Both must return 1024-dimensional, L2-normalized vectors for the same text.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from functools import lru_cache
from typing import Protocol

from loguru import logger


DEFAULT_LOCAL_MODEL = "BAAI/bge-m3"
# ADR-0020: the local runtime and the TEI runtime must share one revision.
DEFAULT_LOCAL_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
EMBEDDING_DIMENSION = 1024
LOCAL_BATCH_SIZE = 16
MAX_TEXT_LENGTH = 8192
DEFAULT_CPU_THREADS = 4
DEFAULT_TEI_BATCH_SIZE = 16
TEI_NORM_TOLERANCE = 1e-5


def _cpu_thread_budget() -> int:
    """Return the bounded CPU thread budget for the embedding runtime."""

    raw = os.environ.get("EMBEDDING_CPU_THREADS", "").strip()
    if raw:
        try:
            threads = int(raw)
        except ValueError as exc:
            raise RuntimeError("EMBEDDING_CPU_THREADS must be a positive integer") from exc
        if threads < 1:
            raise RuntimeError("EMBEDDING_CPU_THREADS must be a positive integer")
        return threads
    return min(DEFAULT_CPU_THREADS, os.cpu_count() or 1)


def _configure_cpu_threads() -> int:
    """Pin OpenMP/BLAS threads before torch is imported.

    The CPU torch runtime used by this project raises a native access violation on some
    hosts when it is allowed to use every logical core, so the thread budget is applied to
    the process environment before the first torch import and mirrored onto torch itself.
    """

    threads = _cpu_thread_budget()
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(variable, str(threads))
    return threads


CPU_THREADS = _configure_cpu_threads()


def _model_dimension(model) -> int:
    getter = getattr(model, "get_embedding_dimension", None)
    if getter is None:
        getter = model.get_sentence_embedding_dimension
    return int(getter())


def _pin_torch_threads() -> None:
    """Apply the CPU thread budget to an already imported torch runtime."""

    try:
        import torch
    except ImportError:
        return
    try:
        torch.set_num_threads(CPU_THREADS)
    except Exception:  # pragma: no cover - defensive: torch may reject late calls
        logger.warning("could not pin torch CPU threads to {}", CPU_THREADS)


def _detect_device() -> str:
    requested = os.environ.get("EMBEDDING_DEVICE", "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        raise RuntimeError("EMBEDDING_DEVICE must be auto, cpu, or cuda")
    if requested == "cpu":
        _pin_torch_threads()
        return "cpu"
    try:
        import torch
    except ImportError:
        if requested == "cuda":
            raise RuntimeError("CUDA embedding requested but torch is unavailable")
        _pin_torch_threads()
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA embedding requested but CUDA is unavailable")
    if torch.cuda.is_available():
        return "cuda"
    _pin_torch_threads()
    return "cpu"


class LocalEmbeddingBackend:
    """Lazy, offline-only SentenceTransformer adapter (rollback runtime)."""

    def __init__(
        self,
        model_name: str = DEFAULT_LOCAL_MODEL,
        revision: str = DEFAULT_LOCAL_MODEL_REVISION,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.device = _detect_device()
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for the local bge-m3 rollback path; "
                "install requirements-scenic-agent-local-embeddings.txt and rebuild the "
                "image with LOCAL_EMBEDDINGS=true, or configure SCENIC_TEI_EMBEDDING_URL"
            ) from exc
        started = time.time()
        self._model = SentenceTransformer(
            self.model_name,
            device=self.device,
            local_files_only=True,
            revision=self.revision,
        )
        dimension = _model_dimension(self._model)
        if dimension != EMBEDDING_DIMENSION:
            self._model = None
            raise RuntimeError(
                f"bge-m3 model dimension must be {EMBEDDING_DIMENSION}, got {dimension}"
            )
        logger.info(
            "local bge-m3 loaded: model={} device={} elapsed={:.1f}s",
            self.model_name,
            self.device,
            time.time() - started,
        )
        return self._model

    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load_model()
        vectors = model.encode(
            [text[:MAX_TEXT_LENGTH] for text in texts],
            batch_size=LOCAL_BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        result = [vector.astype("float32").tolist() for vector in vectors]
        if any(len(vector) != EMBEDDING_DIMENSION for vector in result):
            raise RuntimeError("bge-m3 returned an invalid vector dimension")
        return result

    def probe(self) -> dict[str, object]:
        model = self._load_model()
        return {
            "status": "READY",
            "model": self.model_name,
            "revision": self.revision,
            "device": self.device,
            "dimension": _model_dimension(model),
        }


class EmbeddingBackend(Protocol):
    """The seam the vector store depends on; the runtime behind it may change."""

    model_name: str

    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]: ...

    def probe(self) -> dict[str, object]: ...


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _vector_number(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("TEI returned a non-numeric vector component") from exc
    if not math.isfinite(number):
        raise RuntimeError("TEI returned a non-finite vector component")
    return number


class TEIEmbeddingBackend:
    """bge-m3 served by text-embeddings-inference over HTTP.

    The vector dimension, normalization and text-length semantics stay identical to the
    local sentence-transformers backend, so callers cannot tell the two apart.
    """

    model_name = "BAAI/bge-m3"

    def __init__(
        self,
        *,
        base_url: str,
        revision: str = DEFAULT_LOCAL_MODEL_REVISION,
        timeout: float | None = None,
        batch_size: int | None = None,
        max_text_length: int = MAX_TEXT_LENGTH,
        transport=None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.revision = revision
        self.timeout = float(
            timeout
            if timeout is not None
            else os.environ.get("TEI_EMBEDDING_TIMEOUT", "20")
        )
        self.batch_size = int(
            batch_size
            if batch_size is not None
            else _positive_int_env("TEI_MAX_CLIENT_BATCH_SIZE", DEFAULT_TEI_BATCH_SIZE)
        )
        self.max_text_length = max_text_length
        self._transport = transport

    def _client(self):
        if self._transport is not None:
            return self._transport
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx is a hard dependency
            raise RuntimeError("httpx is required for the TEI embedding backend") from exc
        return httpx.Client(timeout=self.timeout)

    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prepared = [str(text)[: self.max_text_length] for text in texts]
        vectors: list[list[float]] = []
        client = self._client()
        owns_client = self._transport is None
        try:
            for start in range(0, len(prepared), self.batch_size):
                chunk = prepared[start : start + self.batch_size]
                vectors.extend(self._embed_chunk(client, chunk))
        finally:
            if owns_client:
                close = getattr(client, "close", None)
                if callable(close):
                    close()

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"TEI returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        return vectors

    def _embed_chunk(self, client, chunk: list[str]) -> list[list[float]]:
        try:
            response = client.post(f"{self.base_url}/embed", json={"inputs": chunk})
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"TEI embedding request failed: {type(exc).__name__}") from exc
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("TEI embedding response was not valid JSON") from exc
        if not isinstance(payload, list):
            raise RuntimeError("TEI embedding response must be a list of vectors")
        if len(payload) != len(chunk):
            raise RuntimeError(
                f"TEI returned {len(payload)} vectors for {len(chunk)} inputs"
            )
        return [self._validated_vector(vector) for vector in payload]

    @staticmethod
    def _validated_vector(raw: object) -> list[float]:
        if not isinstance(raw, list) or len(raw) != EMBEDDING_DIMENSION:
            size = len(raw) if isinstance(raw, list) else 0
            raise RuntimeError(
                f"TEI returned {size} dimensions; expected {EMBEDDING_DIMENSION}"
            )
        vector = [_vector_number(value) for value in raw]
        norm = math.sqrt(sum(value * value for value in vector))
        if abs(norm - 1) > TEI_NORM_TOLERANCE:
            raise RuntimeError("TEI returned a vector that is not normalized")
        return vector

    def probe(self) -> dict[str, object]:
        """Report what the service actually serves.

        TEI's `/info` does not publish the embedding dimension, so the dimension is
        measured with one real embed call instead of being assumed. A probe that cannot
        measure 1024 normalized dimensions is a failure, not a warning.
        """

        client = self._client()
        owns_client = self._transport is None
        try:
            try:
                info_response = client.get(f"{self.base_url}/info")
                info_response.raise_for_status()
                info = info_response.json()
            except Exception as exc:
                raise RuntimeError(
                    f"TEI embedding probe failed: {type(exc).__name__}"
                ) from exc
            vectors = self._embed_chunk(client, ["dimension probe"])
        finally:
            if owns_client:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
        if not isinstance(info, dict):
            raise RuntimeError("TEI embedding probe returned an unexpected payload")
        dimension = len(vectors[0]) if vectors else 0
        if dimension != EMBEDDING_DIMENSION:
            raise RuntimeError(
                f"TEI embedding service returns {dimension} dimensions; "
                f"expected {EMBEDDING_DIMENSION}"
            )
        model_type = info.get("model_type")
        pooling = None
        if isinstance(model_type, dict):
            embedding = model_type.get("embedding")
            if isinstance(embedding, dict):
                pooling = embedding.get("pooling")
        return {
            "status": "READY",
            "model": str(
                info.get("model_id") or info.get("served_model_name") or self.model_name
            ),
            "revision": self.revision,
            "dimension": dimension,
            "pooling": pooling,
            "max_input_length": info.get("max_input_length"),
        }


def build_embedding_backend() -> EmbeddingBackend:
    """Pick the TEI adapter when a URL is configured, else the local rollback runtime."""

    base_url = os.environ.get("SCENIC_TEI_EMBEDDING_URL", "").strip()
    if base_url:
        return TEIEmbeddingBackend(base_url=base_url)
    return LocalEmbeddingBackend(os.environ.get("BGE_M3_MODEL_PATH", DEFAULT_LOCAL_MODEL))


class EmbeddingClient:
    def __init__(self, backend: EmbeddingBackend | None = None) -> None:
        self.backend = backend or build_embedding_backend()

    async def embed_text(self, text: str) -> list[float]:
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.backend.embed_batch_sync, texts)

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIMENSION


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    return EmbeddingClient()


__all__ = [
    "DEFAULT_LOCAL_MODEL",
    "DEFAULT_LOCAL_MODEL_REVISION",
    "EMBEDDING_DIMENSION",
    "EmbeddingBackend",
    "EmbeddingClient",
    "LocalEmbeddingBackend",
    "MAX_TEXT_LENGTH",
    "TEIEmbeddingBackend",
    "build_embedding_backend",
    "get_embedding_client",
]
