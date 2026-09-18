"""External-behaviour tests for the TEI reranker adapter."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from memory_palace.knowledge.reranking import (
    NoopRerankerBackend,
    TEIRerankerBackend,
    build_reranker_backend,
)


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list = []


def _start_tei(recorder: _Recorder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _tei(recorder: _Recorder, **kwargs):
    server, thread = _start_tei(recorder)
    port = server.server_address[1]
    return TEIRerankerBackend(base_url=f"http://127.0.0.1:{port}", **kwargs), server


def _candidates() -> list[dict]:
    return [
        {"id": "a", "text": "alpha", "metadata": {"venue_id": "v1"}},
        {"id": "b", "text": "beta", "metadata": {"venue_id": "v1"}},
        {"id": "c", "text": "gamma", "metadata": {"venue_id": "v1"}},
    ]


def test_empty_candidates_short_circuit_without_http():
    recorder = _Recorder()
    backend, server = _tei(recorder)
    try:
        assert backend.rerank_sync("q", [], top_n=3) == []
    finally:
        server.shutdown()
    assert recorder.requests == []


def test_scores_map_back_to_original_candidates_and_sort_descending():
    recorder = _Recorder()
    recorder.responses = [
        [{"index": 0, "score": 0.1}, {"index": 2, "score": 0.9}, {"index": 1, "score": 0.5}]
    ]
    backend, server = _tei(recorder)
    try:
        ranked = backend.rerank_sync("q", _candidates(), top_n=3)
    finally:
        server.shutdown()

    assert [item["id"] for item in ranked] == ["c", "b", "a"]
    assert ranked[0]["rerank_score"] == pytest.approx(0.9)
    assert ranked[0]["metadata"] == {"venue_id": "v1"}
    assert recorder.requests[0]["body"]["query"] == "q"
    assert recorder.requests[0]["body"]["texts"] == ["alpha", "beta", "gamma"]


def test_top_n_limits_the_returned_candidates():
    recorder = _Recorder()
    recorder.responses = [
        [{"index": 0, "score": 0.1}, {"index": 2, "score": 0.9}, {"index": 1, "score": 0.5}]
    ]
    backend, server = _tei(recorder)
    try:
        ranked = backend.rerank_sync("q", _candidates(), top_n=2)
    finally:
        server.shutdown()
    assert [item["id"] for item in ranked] == ["c", "b"]


def test_duplicate_indexes_are_deduplicated():
    recorder = _Recorder()
    recorder.responses = [[{"index": 1, "score": 0.9}, {"index": 1, "score": 0.8}]]
    backend, server = _tei(recorder)
    try:
        ranked = backend.rerank_sync("q", _candidates(), top_n=3)
    finally:
        server.shutdown()
    assert [item["id"] for item in ranked] == ["b"]
    assert ranked[0]["rerank_score"] == pytest.approx(0.9)


def test_out_of_range_index_is_rejected():
    recorder = _Recorder()
    recorder.responses = [[{"index": 9, "score": 0.9}]]
    backend, server = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.rerank_sync("q", _candidates(), top_n=3)
    finally:
        server.shutdown()


def test_http_failure_raises_so_callers_can_fall_back():
    recorder = _Recorder()
    recorder.responses = [(500, {"error": "boom"})]
    backend, server = _tei(recorder)
    try:
        with pytest.raises(RuntimeError):
            backend.rerank_sync("q", _candidates(), top_n=3)
    finally:
        server.shutdown()


def test_noop_backend_keeps_vector_order_and_marks_disabled():
    ranked = NoopRerankerBackend().rerank_sync("q", _candidates(), top_n=2)
    assert [item["id"] for item in ranked] == ["a", "b"]
    assert all(item["rerank_status"] == "DISABLED" for item in ranked)


def test_factory_selects_tei_when_url_is_configured(monkeypatch):
    monkeypatch.setenv("SCENIC_TEI_RERANKER_URL", "http://tei-reranker:80")
    assert isinstance(build_reranker_backend(), TEIRerankerBackend)


def test_factory_returns_noop_when_url_is_absent(monkeypatch):
    monkeypatch.delenv("SCENIC_TEI_RERANKER_URL", raising=False)
    assert isinstance(build_reranker_backend(), NoopRerankerBackend)
