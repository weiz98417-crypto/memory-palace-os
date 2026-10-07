"""Isolated OpenAI-compatible failure endpoint for UAT fault injection."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FaultHandler(BaseHTTPRequestHandler):
    mode = "unauthorized"

    def do_POST(self) -> None:
        if self.path in {"/mode/unauthorized", "/mode/timeout"}:
            type(self).mode = self.path.rsplit("/", 1)[-1]
            self._respond(200, {"mode": type(self).mode})
            return
        if self.path != "/v1/chat/completions":
            self._respond(404, {"error": {"message": "not found"}})
            return
        if type(self).mode == "timeout":
            time.sleep(8)
        self._respond(401, {"error": {"message": "UAT injected unauthorized", "type": "authentication_error", "code": "invalid_api_key"}})

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8099), FaultHandler).serve_forever()
