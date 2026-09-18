"""External-behaviour tests for the TEI embedding adapter."""

from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from memory_palace.tools.embedding_client import (
    EMBEDDING_DIMENSION,
    TEIEmbeddingBackend,
    build_embedding_backend,
)


def _vector(seed: float) -> list[float]:
    """An L2-normalized unit vector whose second component is exactly ``seed``."""
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[0] = math.sqrt(max(0.0, 1.0 - seed * seed))
    vector[1] = seed
    return vector


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list = []


def _start_tei(recorder: _Recorder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence test output
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            recorder.requests.append({"path": self.path, "body": body})
            payload = recorder.responses.pop(0)
            status = 200
            if isinstance(payload, tuple):
                status, payload = payload
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            recorder.requests.append({"path": self.path, "body": None})
            payload = recorder.responses.pop(0)
            status = 200
            if isinstance(payload, tuple):
                status, payload = payload
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _tei(recorder: _Recorder, **kwargs):
    server, thread = _start_tei(recorder)
    port = server.server_address[1]
    backend = TEIEmbeddingBackend(
        base_url=f"http://127.0.0.1:{port}", **kwargs
    )
    return backend, server, thread


def test_empty_batch_short_circuits_without_http():
    recorder = _Recorder()
    backend, server, _ = _tei(recorder)
    try:
        assert backend.embed_batch_sync([]) == []
    finally:
        server.shutdown()
    assert recorder.requests == []


def test_batch_is_chunked_and_order_is_preserved():
    recorder = _Recorder()
    recorder.responses = [
        [_vector(0.1), _vector(0.2)],
        [_vector(0.3)],
    ]
    backend, server, _ = _tei(recorder, batch_size=2)
    try:
        vectors = backend.embed_batch_sync(["a", "b", "c"])
    finally:
        server.shutdown()

    assert len(vectors) == 3
    assert vectors[0][1] == pytest.approx(0.1)
    assert vectors[2][1] == pytest.approx(0.3)
    assert [r["body"]["inputs"] for r in recorder.requests] == [["a", "b"], ["c"]]


def test_long_text_is_truncated_before_http():
    recorder = _Recorder()
    recorder.responses = [[_vector(0.5)]]
    backend, server, _ = _tei(recorder, max_text_length=4)
    try:
        backend.embed_batch_sync(["abcdefgh"])
    finally:
        server.shutdown()
    assert recorder.requests[0]["body"]["inputs"] == ["abcd"]


def test_wrong_dimension_is_rejected_instead_of_padded():
    recorder = _Recorder()
    recorder.responses = [[[0.1, 0.2, 0.3]]]
    backend, server, _ = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.embed_batch_sync(["a"])
    finally:
        server.shutdown()


def test_non_finite_vector_is_rejected():
    recorder = _Recorder()
    recorder.responses = [[_vector(float("inf"))]]
    backend, server, _ = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.embed_batch_sync(["a"])
    finally:
        server.shutdown()


def test_denormalised_vector_is_rejected():
    recorder = _Recorder()
    recorder.responses = [[[3.0] * EMBEDDING_DIMENSION]]
    backend, server, _ = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.embed_batch_sync(["a"])
    finally:
        server.shutdown()


def test_http_failure_raises_and_does_not_silently_return_vectors():
    recorder = _Recorder()
    recorder.responses = [(500, {"error": "boom"})]
    backend, server, _ = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.embed_batch_sync(["a"])
    finally:
        server.shutdown()


def test_incomplete_response_is_rejected():
    recorder = _Recorder()
    recorder.responses = [[_vector(0.1)]]
    backend, server, _ = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.embed_batch_sync(["a", "b"])
    finally:
        server.shutdown()


def test_probe_measures_the_dimension_with_a_real_embed_call():
    """TEI's /info does not publish a dimension, so the adapter must measure it."""

    recorder = _Recorder()
    recorder.responses = [
        {
            "model_id": "BAAI/bge-m3",
            "model_type": {"embedding": {"pooling": "cls"}},
            "max_input_length": 2048,
        },
        [_vector(0.5)],
    ]
    backend, server, _ = _tei(recorder, revision="rev-123")
    try:
        probe = backend.probe()
    finally:
        server.shutdown()
    assert probe["status"] == "READY"
    assert probe["model"] == "BAAI/bge-m3"
    assert probe["dimension"] == EMBEDDING_DIMENSION
    assert probe["revision"] == "rev-123"
    assert probe["pooling"] == "cls"
    assert [request["path"] for request in recorder.requests] == ["/info", "/embed"]


def test_probe_fails_when_the_service_serves_the_wrong_dimension():
    recorder = _Recorder()
    recorder.responses = [
        {"model_id": "BAAI/bge-m3"},
        [[0.1, 0.2, 0.3]],
    ]
    backend, server, _ = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.probe()
    finally:
        server.shutdown()


def test_backend_factory_selects_tei_when_url_is_configured(monkeypatch):
    monkeypatch.setenv("SCENIC_TEI_EMBEDDING_URL", "http://tei-embedding:80")
    backend = build_embedding_backend()
    assert isinstance(backend, TEIEmbeddingBackend)


def test_backend_factory_falls_back_to_local_when_url_is_absent(monkeypatch):
    monkeypatch.delenv("SCENIC_TEI_EMBEDDING_URL", raising=False)
    backend = build_embedding_backend()
    assert type(backend).__name__ == "LocalEmbeddingBackend"
