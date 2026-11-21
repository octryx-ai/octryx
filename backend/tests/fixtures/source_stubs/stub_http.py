"""The shared HTTP side of the source-system stubs (Confluence, Jira) of the local acceptance stack.

A stub is a pure ``handle(method, target, authorization) -> (status, JSON body)`` function over
fixed fixtures; this module serves it with the standard library only and adds what every stub has:

- ``GET /healthz``: unauthenticated liveness for the compose health check;
- ``GET /_stub/requests``: unauthenticated, what the stub was asked so far (method counts and the
  bounded list of ``METHOD path`` lines, never a header or query value). The acceptance check reads
  it from inside the stub's container, to prove the connectors only ever sent ``GET``;
- a Basic credential check (``basic_authorization``) the stubs apply to everything else.

Every HTTP method is dispatched to ``handle``, so a write reaches the stub, is recorded, and is
refused (405). The log line is method, path and status only.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
from collections import Counter
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

Handle = Callable[[str, str, str | None], tuple[int, dict]]
MAX_RECORDED_REQUESTS = 500
_UNRECORDED = frozenset({"/healthz", "/_stub/requests"})


def basic_authorization(username: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{token}".encode()).decode()


def split_target(target: str) -> tuple[str, dict[str, list[str]]]:
    parts = urlsplit(target)
    return parts.path.rstrip("/") or "/", parse_qs(parts.query)


def bounded_int(query: dict[str, list[str]], name: str, default: int) -> int | None:
    raw = (query.get(name) or [str(default)])[0]
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


class RequestLog:
    """What a stub was asked: method counts and ``METHOD path`` lines, bounded, thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._methods: Counter[str] = Counter()
        self._lines: list[str] = []

    def record(self, method: str, path: str) -> None:
        with self._lock:
            self._methods[method] += 1
            if len(self._lines) < MAX_RECORDED_REQUESTS:
                self._lines.append(f"{method} {path}")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"methods": dict(self._methods), "requests": list(self._lines)}


def serve(handle: Handle, *, name: str, host: str, port: int) -> int:
    log = RequestLog()

    class _Handler(BaseHTTPRequestHandler):
        server_version = name
        sys_version = ""

        def _answer(self) -> None:
            path, _ = split_target(self.path)
            if path == "/_stub/requests" and self.command == "GET":
                status, payload = 200, log.snapshot()
            else:
                if path not in _UNRECORDED:
                    log.record(self.command, path)
                status, payload = handle(self.command, self.path, self.headers.get("Authorization"))
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            # Method, path and status only: never a header, so never the Authorization value.
            status = args[1] if len(args) > 1 else "-"
            sys.stdout.write(f"{self.command} {urlsplit(self.path).path} {status}\n")
            sys.stdout.flush()

    # http.server dispatches to ``do_<METHOD>``; every method gets the stub's answer (a write: 405).
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        setattr(_Handler, f"do_{method}", _Handler._answer)

    server = ThreadingHTTPServer((host, port), _Handler)
    sys.stdout.write(f"{name} listening on {host}:{port}\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
