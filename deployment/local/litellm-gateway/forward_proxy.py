"""A minimal loopback CONNECT proxy for the qualification fixture.

The governed proxy option is only meaningfully proven if a real proxy hop carries
the call: the client must open a ``CONNECT`` tunnel to the configured proxy and
reach the gateway through it. This proxy records the tunnel targets it was asked
for, which is how the smoke shows that

- a governed-proxy configuration really routes through the proxy, and
- a direct configuration does not touch it, even with hostile ambient
  ``HTTP_PROXY``/``HTTPS_PROXY``/``ALL_PROXY`` variables exported.

It is a test double: tunnels are only opened to an explicit allowlist of loopback
targets, the TLS payload is forwarded byte for byte and never inspected (the
virtual key travels inside it), and nothing is logged.
"""

from __future__ import annotations

import socket
import threading

BUFFER_BYTES = 65536
CONNECT_TIMEOUT_SECONDS = 5.0


class LocalConnectProxy:
    """Context manager owning the proxy listener thread."""

    def __init__(self, *, allowed_targets: tuple[tuple[str, int], ...]):
        self._allowed = set(allowed_targets)
        self._lock = threading.Lock()
        self._targets: list[str] = []
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(16)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="litellm-fixture-proxy", daemon=True)

    @property
    def port(self) -> int:
        return int(self._listener.getsockname()[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def tunnel_targets(self) -> list[str]:
        with self._lock:
            return list(self._targets)

    def reset(self) -> None:
        with self._lock:
            self._targets.clear()

    def __enter__(self) -> LocalConnectProxy:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        try:
            self._listener.close()
        except OSError:
            pass
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _address = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            client.settimeout(CONNECT_TIMEOUT_SECONDS)
            request = b""
            while b"\r\n\r\n" not in request and len(request) < BUFFER_BYTES:
                chunk = client.recv(BUFFER_BYTES)
                if not chunk:
                    return
                request += chunk
            line = request.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
            method, _, rest = line.partition(" ")
            authority = rest.partition(" ")[0]
            if method.upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
                return
            host, _, raw_port = authority.rpartition(":")
            try:
                port = int(raw_port)
            except ValueError:
                client.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                return
            with self._lock:
                self._targets.append(f"{host}:{port}")
            if (host, port) not in self._allowed:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                return
            upstream = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS)
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self._pump(client, upstream)
        except (OSError, UnicodeDecodeError):
            return
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

    @staticmethod
    def _pump(left: socket.socket, right: socket.socket) -> None:
        """Forward the tunnel in both directions without inspecting a byte."""

        done = threading.Event()

        def copy(source: socket.socket, destination: socket.socket) -> None:
            try:
                while not done.is_set():
                    chunk = source.recv(BUFFER_BYTES)
                    if not chunk:
                        break
                    destination.sendall(chunk)
            except OSError:
                pass
            finally:
                done.set()

        forward = threading.Thread(target=copy, args=(left, right), daemon=True)
        backward = threading.Thread(target=copy, args=(right, left), daemon=True)
        forward.start()
        backward.start()
        forward.join()
        backward.join(timeout=1)


__all__ = ["LocalConnectProxy"]
