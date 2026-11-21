"""The session's hook signer: an HMAC key that lives only in the supervisor's memory.

The launcher (the supervisor) generates a per-session ``hook_key``, registers it with
the platform (``POST /sessions/hook-key``, set once per session) and serves signatures
over a Unix domain socket at ``sessions/<key>/hook.sock`` (directory 0700, socket 0600).
The key is never written to a file, an environment variable, argv or a log, so a
process that holds only the session's tokens cannot forge a confirmation proof.

Protocol: one JSON line ``{"op": "sign", "message": str}`` per connection, one JSON line
answer ``{"mac": hex}`` or ``{"error": "<code>"}``. Only workflow confirmation and run decision messages
of this session are signed:

    v1|confirm|<session_key>|<tool_use_id>|<approval_id>|<nonce_hex32>|<unix_ts>
    v1|decide|<session_key>|<tool_use_id>|<run_id>|<nonce_hex32>|<unix_ts>
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Any

from .state import LocalState

SOCKET_NAME = "hook.sock"
HOOK_KEY_BYTES = 32
MAX_REQUEST_BYTES = 4 * 1024
CONNECTION_TIMEOUT = 2.0
ACCEPT_POLL_SECONDS = 0.25
# sockaddr_un.sun_path is 104 bytes on macOS (108 on Linux), including the NUL.
MAX_SOCKET_PATH_BYTES = 103
_SOCKET_MODE = 0o600

_MAC = re.compile(r"^[0-9a-f]{64}$")


class SignerUnavailableError(Exception):
    """The signer cannot be started; ``code`` is fixed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def new_hook_key() -> bytes:
    return secrets.token_bytes(HOOK_KEY_BYTES)


def encode_hook_key(hook_key: bytes) -> str:
    """base64url without padding, as the platform expects it."""
    return base64.urlsafe_b64encode(hook_key).decode("ascii").rstrip("=")


def socket_path(state: LocalState, session_key: str) -> Path:
    return state.session_dir(session_key) / SOCKET_NAME


def _message_pattern(session_key: str) -> re.Pattern[str]:
    return re.compile(
        rf"v1\|(confirm|decide)\|{re.escape(session_key)}\|[A-Za-z0-9_\-]{{1,64}}\|[A-Za-z0-9\-]{{1,36}}"
        r"\|[0-9a-f]{32}\|[0-9]{10}"
    )


def confirm_message(session_key: str, tool_use_id: str, approval_id: str, nonce: str, ts: int,
                    verb: str = "confirm") -> str:
    return f"v1|{verb}|{session_key}|{tool_use_id}|{approval_id}|{nonce}|{ts}"


def _read_line(conn: socket.socket) -> bytes | None:
    """The request line, or ``None`` when it exceeds ``MAX_REQUEST_BYTES``."""
    buffer = b""
    while b"\n" not in buffer:
        chunk = conn.recv(MAX_REQUEST_BYTES + 1)
        if not chunk:
            break
        buffer += chunk
        if len(buffer) > MAX_REQUEST_BYTES:
            return None
    line = buffer.split(b"\n", 1)[0]
    return line if len(line) <= MAX_REQUEST_BYTES else None


class Signer:
    """Serves signatures for one session until ``close``; never raises out of its thread."""

    def __init__(self, path: Path, session_key: str, hook_key: bytes) -> None:
        self.path = path
        self._session_key = session_key
        self._hook_key = hook_key
        self._pattern = _message_pattern(session_key)
        self._stop = threading.Event()
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Signer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def respond(self, raw: bytes | None) -> dict[str, str]:
        if raw is None:
            return {"error": "request_too_large"}
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {"error": "invalid_request"}
        if not isinstance(request, dict) or request.get("op") != "sign":
            return {"error": "invalid_request"}
        message = request.get("message")
        if not isinstance(message, str) or not self._pattern.fullmatch(message):
            return {"error": "message_refused"}
        return {"mac": hmac.new(self._hook_key, message.encode("utf-8"), hashlib.sha256).hexdigest()}

    def start(self) -> Signer:
        if len(os.fsencode(str(self.path))) > MAX_SOCKET_PATH_BYTES:
            raise SignerUnavailableError("socket_path_too_long")
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.path))
            os.chmod(self.path, _SOCKET_MODE)
            listener.listen(8)
            listener.settimeout(ACCEPT_POLL_SECONDS)
        except OSError as exc:
            listener.close()
            with contextlib.suppress(OSError):
                os.unlink(self.path)
            raise SignerUnavailableError("socket_bind_failed") from exc
        self._listener = listener
        self._thread = threading.Thread(target=self._serve, args=(listener,), name="octryx-hook-signer",
                                        daemon=True)
        self._thread.start()
        return self

    def _serve(self, listener: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001 - the signer thread never dies on a socket error
                if self._stop.is_set():
                    return
                time.sleep(ACCEPT_POLL_SECONDS)
                continue
            try:
                with conn:
                    conn.settimeout(CONNECTION_TIMEOUT)
                    answer = self.respond(_read_line(conn))
                    conn.sendall((json.dumps(answer) + "\n").encode("utf-8"))
            except Exception:  # noqa: BLE001 - one bad connection never stops the signer
                continue

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2 * ACCEPT_POLL_SECONDS + CONNECTION_TIMEOUT)
        if self._listener is not None:
            with contextlib.suppress(OSError):
                self._listener.close()
        with contextlib.suppress(OSError):
            os.unlink(self.path)


def start_signer(state: LocalState, session_key: str, hook_key: bytes) -> Signer:
    return Signer(socket_path(state, session_key), session_key, hook_key).start()


# --- client side (the PreToolUse hook) -------------------------------------------


def sign(state: LocalState, session_key: str, message: str, timeout: float = 3) -> str | None:
    """The supervisor's mac for ``message``, or ``None`` when it is unreachable or refuses."""
    try:
        path = socket_path(state, session_key)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(str(path))
            conn.sendall((json.dumps({"op": "sign", "message": message}) + "\n").encode("utf-8"))
            raw = _read_line(conn)
        answer: Any = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:  # noqa: BLE001 - any failure means "no proof"; the hook fails closed
        return None
    mac = answer.get("mac") if isinstance(answer, dict) else None
    return mac if isinstance(mac, str) and _MAC.match(mac) else None


def confirmation_proof(state: LocalState, session_key: str, tool_use_id: object,
                       approval_id: object, verb: str = "confirm") -> dict[str, Any] | None:
    """``{"nonce", "ts", "mac"}`` for a ``workflow_confirm`` call (verb ``decide``: a ``workflow_decide`` call bound
    to its run id), or ``None`` (fail closed)."""
    if not isinstance(tool_use_id, str) or not isinstance(approval_id, str):
        return None
    nonce = secrets.token_hex(16)
    ts = int(time.time())
    mac = sign(state, session_key, confirm_message(session_key, tool_use_id, approval_id, nonce, ts, verb))
    if mac is None:
        return None
    return {"nonce": nonce, "ts": ts, "mac": mac}
