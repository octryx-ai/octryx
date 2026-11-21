"""A deterministic LiteLLM-compatible HTTPS endpoint on loopback.

Real socket, real TLS handshake, real HTTP framing — the product client is not
given an injected transport, so the trust store, the proxy hop, the request paths
and the response contract are all exercised the way they will be in a cluster.

Boundaries:

- the request log records method, path and whether the ``Authorization`` header
  matched the expected bearer. The header value itself is never stored or printed;
- request bodies are parsed to pick the scenario and then dropped;
- the stdlib request logger is silenced, so no header or path lands in a log.
"""

from __future__ import annotations

import json
import ssl
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fixture_contract import HOST, catalog_payload, chat_payload

MODELS_PATH = "/v1/models"
CHAT_PATH = "/v1/chat/completions"
MAX_REQUEST_BYTES = 256 * 1024


@dataclass(frozen=True)
class ObservedRequest:
    method: str
    path: str
    authorization_matched: bool
    model_group: str


class _GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LiteLLMFixture/1.0"
    sys_version = ""

    # Never log a request line: it would put paths (and, with a malformed client,
    # header material) into the run output.
    def log_message(self, _format: str, *_args: Any) -> None:
        return

    @property
    def _state(self) -> _FixtureState:
        return self.server.fixture_state  # type: ignore[attr-defined]

    def _authorization_matched(self) -> bool:
        header = self.headers.get("Authorization") or ""
        return header == f"Bearer {self._state.virtual_key}"

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        matched = self._authorization_matched()
        self._state.record(ObservedRequest("GET", self.path, matched, ""))
        if not matched:
            self._respond(401, {"error": {"code": "invalid_api_key", "message": "fixture rejected the key"}})
            return
        if self.path != MODELS_PATH:
            self._respond(404, {"error": {"code": "not_found"}})
            return
        self._respond(200, catalog_payload())

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        matched = self._authorization_matched()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(length, MAX_REQUEST_BYTES)) if length > 0 else b""
        model_group = ""
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
            if isinstance(parsed, dict):
                model_group = str(parsed.get("model") or "")
        except (UnicodeDecodeError, ValueError):
            model_group = ""
        # The parsed body is dropped here: only the model group survives, because
        # it selects the scenario. Messages and tools are never retained.
        self._state.record(ObservedRequest("POST", self.path, matched, model_group))
        if not matched:
            self._respond(401, {"error": {"code": "invalid_api_key", "message": "fixture rejected the key"}})
            return
        if self.path != CHAT_PATH:
            self._respond(404, {"error": {"code": "not_found"}})
            return
        self._respond(200, chat_payload(model_group))


class _FixtureState:
    def __init__(self, virtual_key: str):
        self.virtual_key = virtual_key
        self._lock = threading.Lock()
        self._requests: list[ObservedRequest] = []

    def record(self, request: ObservedRequest) -> None:
        with self._lock:
            self._requests.append(request)

    @property
    def requests(self) -> list[ObservedRequest]:
        with self._lock:
            return list(self._requests)

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()


class LocalGatewayFixture:
    """Context manager owning the TLS server thread."""

    def __init__(self, *, virtual_key: str, certificate_path: Path, key_path: Path):
        self._state = _FixtureState(virtual_key)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(certificate_path), keyfile=str(key_path))
        self._server = ThreadingHTTPServer((HOST, 0), _GatewayHandler)
        self._server.fixture_state = self._state  # type: ignore[attr-defined]
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, name="litellm-fixture", daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def requests(self) -> list[ObservedRequest]:
        return self._state.requests

    def reset(self) -> None:
        self._state.reset()

    def __enter__(self) -> LocalGatewayFixture:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


__all__ = ["CHAT_PATH", "MODELS_PATH", "LocalGatewayFixture", "ObservedRequest"]
