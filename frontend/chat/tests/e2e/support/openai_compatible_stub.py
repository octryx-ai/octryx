"""Loopback OpenAI-compatible provider stub for unmocked browser acceptance.

Stdlib only. It stands in for a model gateway so a browser acceptance run can
drive real chat turns through the platform's own provider configuration and
admission without any cloud credentials:

- ``GET  /v1/models``            OpenAI model list with LiteLLM ``model_info``
                                 capability evidence for one model group.
- ``POST /v1/chat/completions``  deterministic assistant answer (JSON, or SSE
                                 when the request sets ``stream: true``); in
                                 ``fail`` mode a fixed HTTP 503 error.
- ``GET  /__stub/mode``          current mode.
- ``POST /__stub/mode``          ``{"mode": "ok" | "fail"}`` switches the mode.
- ``GET  /__stub/requests``      per-route request counters.

It binds to 127.0.0.1 only. When ``--api-key`` is given, provider routes refuse
requests without that bearer token, which proves the platform resolved the
provider credential from its own secret store.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE_OK = "ok"
MODE_FAIL = "fail"
MODES = frozenset({MODE_OK, MODE_FAIL})

ANSWER_TEXT = "Stub provider answer for the acceptance run."
PROMPT_TOKENS = 42
COMPLETION_TOKENS = 9


class StubState:
    """Mode and request counters, shared across handler threads."""

    def __init__(self, *, model_group: str, api_key: str) -> None:
        self.model_group = model_group
        self.api_key = api_key
        self._lock = threading.Lock()
        self._mode = MODE_OK
        self._counts = {"chat_completions": 0, "models": 0, "unauthorized": 0}

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode

    def count(self, key: str) -> None:
        with self._lock:
            self._counts[key] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


def build_handler(state: StubState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "OctryxProviderStub/1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict | None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw or b"{}")
            except ValueError:
                return None
            return payload if isinstance(payload, dict) else None

        def _authorized(self) -> bool:
            if not state.api_key:
                return True
            if self.headers.get("Authorization") == f"Bearer {state.api_key}":
                return True
            state.count("unauthorized")
            self._send_json(401, {"error": {"message": "invalid api key", "code": "invalid_api_key"}})
            return False

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/__stub/mode":
                self._send_json(200, {"mode": state.mode})
            elif self.path == "/__stub/requests":
                self._send_json(200, state.snapshot())
            elif self.path == "/v1/models":
                if not self._authorized():
                    return
                state.count("models")
                self._send_json(200, self._model_list())
            else:
                self._send_json(404, {"error": {"message": "not found", "code": "not_found"}})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/__stub/mode":
                payload = self._read_json() or {}
                mode = str(payload.get("mode") or "")
                if mode not in MODES:
                    self._send_json(400, {"error": {"message": "mode must be ok or fail", "code": "bad_mode"}})
                    return
                state.set_mode(mode)
                self._send_json(200, {"mode": mode})
            elif self.path == "/v1/chat/completions":
                if not self._authorized():
                    return
                state.count("chat_completions")
                payload = self._read_json()
                if payload is None:
                    self._send_json(400, {"error": {"message": "invalid json", "code": "invalid_request"}})
                    return
                if state.mode == MODE_FAIL:
                    self._send_json(
                        503,
                        {"error": {"message": "stub provider unavailable", "code": "stub_unavailable"}},
                    )
                    return
                model = str(payload.get("model") or state.model_group)
                if payload.get("stream") is True:
                    self._send_stream(model)
                else:
                    self._send_json(200, self._completion(model))
            else:
                self._send_json(404, {"error": {"message": "not found", "code": "not_found"}})

        def _model_list(self) -> dict:
            return {
                "object": "list",
                "data": [
                    {
                        "id": state.model_group,
                        "object": "model",
                        "owned_by": "octryx-e2e-stub",
                        "model_info": {
                            "supports_function_calling": True,
                            "supports_reasoning": True,
                            "max_input_tokens": 128000,
                        },
                    }
                ],
            }

        @staticmethod
        def _usage() -> dict:
            return {
                "prompt_tokens": PROMPT_TOKENS,
                "completion_tokens": COMPLETION_TOKENS,
                "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
            }

        def _completion(self, model: str) -> dict:
            return {
                "id": "chatcmpl-e2e-stub",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ANSWER_TEXT},
                        "finish_reason": "stop",
                    }
                ],
                "usage": self._usage(),
            }

        def _send_stream(self, model: str) -> None:
            base = {"id": "chatcmpl-e2e-stub", "object": "chat.completion.chunk", "model": model}
            chunks = [
                {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ANSWER_TEXT}}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": self._usage()},
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model-group", default="octryx-e2e-stub-group")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    state = StubState(model_group=args.model_group, api_key=args.api_key)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(state))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
