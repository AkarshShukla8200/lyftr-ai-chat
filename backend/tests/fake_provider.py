"""A local HTTP server that speaks the Gemini generateContent wire format.

Tests point real LiteLLM at it (api_base), so LiteLLM's own request building,
response parsing and exception classification are exercised; nothing leaves
the machine. Behaviour is chosen per API key (x-goog-api-key header).
"""

from __future__ import annotations

import http.server
import json
import threading
import time
from collections import Counter
from typing import Any


def ok_body(text: str = "Hello from fake Gemini.", prompt_tokens: int = 11, output_tokens: int = 4) -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP"}
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
            "totalTokenCount": prompt_tokens + output_tokens,
        },
    }


ERRORS: dict[str, tuple[int, dict]] = {
    "429": (429, {"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}}),
    "quota": (429, {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.", "status": "RESOURCE_EXHAUSTED"}}),
    "500": (500, {"error": {"code": 500, "message": "An internal error has occurred.", "status": "INTERNAL"}}),
    "502": (502, {"error": {"code": 502, "message": "Bad Gateway"}}),
    "503": (503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}}),
    "401": (401, {"error": {"code": 401, "message": "Request had invalid authentication credentials.", "status": "UNAUTHENTICATED"}}),
    "403": (403, {"error": {"code": 403, "message": "Permission denied.", "status": "PERMISSION_DENIED"}}),
    "400_bad_key": (400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT", "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}),
    "empty": (200, {"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 0, "totalTokenCount": 3}}),
    "blocked": (200, {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 3, "totalTokenCount": 3}}),
}


class FakeGemini:
    def __init__(self) -> None:
        self.behaviour: dict[str, str] = {}   # api_key -> "ok" | error name | "slow"
        self.hits: Counter = Counter()
        self.bodies: list[dict[str, Any]] = []
        self.reply_text = "Hello from fake Gemini."
        self.delay_seconds = 0.0
        self._lock = threading.Lock()
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                key = self.headers.get("x-goog-api-key", "")
                with fake._lock:
                    fake.hits[key] += 1
                    fake.bodies.append(body)
                mode = fake.behaviour.get(key, "ok")
                if fake.delay_seconds:
                    time.sleep(fake.delay_seconds)
                if mode == "slow":
                    time.sleep(3)
                    mode = "ok"
                if mode == "ok":
                    status, payload = 200, ok_body(fake.reply_text)
                else:
                    status, payload = ERRORS[mode]
                data = json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # client timed out and closed the socket

            def log_message(self, *args):  # silence
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeGemini":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
