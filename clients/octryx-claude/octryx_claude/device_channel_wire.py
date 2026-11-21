"""The device channel's wire: its constants, the connection interface over ``websockets``, the message envelope and
the handshake read (``device_channel``)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

PROTOCOL_VERSION = 1
CHANNEL_PATH = "/api/v1/devices/channel"
BACKOFF_START = 1.0
BACKOFF_MAX = 30.0
# After an announced platform restart (1012 service restart, 1001 going away): retry every 1-3 s for 3 minutes.
RESTART_CLOSE_CODES = frozenset({1001, 1012})
FAST_RETRY_SECONDS = 2.0
FAST_RETRY_WINDOW_SECONDS = 180.0
LOG_EVERY_SECONDS = 60.0
REVOKED_RECHECK_SECONDS = 15 * 60
REVOKED_RECHECK_MAX_SECONDS = 6 * 60 * 60
REVOKED_RETRY_START = 60.0
HANDSHAKE_TIMEOUT = 20.0
TOKEN_CHECK_SECONDS = 30.0
STATE_CHECK_SECONDS = 5.0
LOCAL_SESSIONS_SECONDS = 30.0  # how often the connected Claude Code profiles are scanned
IDLE_CHECK_SECONDS = 60.0
STATUS_HEARTBEAT_SECONDS = 60.0
NEEDS_LOGIN_RETRY_SECONDS = 60 * 60
NEEDS_LOGIN_CODES = frozenset({"refresh_rejected", "not_logged_in", "renewal_rejected"})
REVOKED_CODE = "device_revoked"
# Close reasons of a grant or token problem (the platform's recheck, a refused handshake): refresh, never revoke.
CREDENTIAL_REFUSALS = frozenset({"device_grant_revoked", "device_grant_expired", "device_login_expired",
                                 "device_token_invalid", "device_scope_missing"})
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_REVOKED = 4410


class ChannelClosedError(Exception):
    def __init__(self, code: int = 1006, reason: str = "") -> None:
        super().__init__(f"{code} {reason}")
        self.code = code
        self.reason = reason


class Connection(Protocol):
    async def send(self, text: str) -> None: ...

    async def recv(self) -> str: ...

    async def close(self) -> None: ...


Connect = Callable[[str, dict[str, str]], Awaitable[Connection]]
TokenProvider = Callable[[bool], str]
RevocationCheck = Callable[[], str]


class _WebsocketsConnection:
    """``websockets`` behind the small ``Connection`` interface; a close becomes ``ChannelClosedError``."""

    def __init__(self, socket: Any) -> None:
        self.socket = socket

    async def send(self, text: str) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            await self.socket.send(text)
        except ConnectionClosed as exc:
            raise ChannelClosedError(*_close_details(exc)) from exc

    async def recv(self) -> str:
        from websockets.exceptions import ConnectionClosed

        try:
            message = await self.socket.recv()
        except ConnectionClosed as exc:
            raise ChannelClosedError(*_close_details(exc)) from exc
        return message if isinstance(message, str) else message.decode("utf-8", errors="replace")

    async def close(self) -> None:
        await self.socket.close()


async def _handshake_message(connection: Any) -> dict[str, Any]:
    """One handshake message. A platform too slow to answer within ``HANDSHAKE_TIMEOUT``, or an unreadable message,
    is a closed channel like any other, so the loop reconnects (it ended the service)."""
    try:
        return json.loads(await asyncio.wait_for(connection.recv(), HANDSHAKE_TIMEOUT))
    except TimeoutError as exc:
        raise ChannelClosedError(1006, "handshake_timeout") from exc
    except ValueError as exc:
        raise ChannelClosedError(4400, "handshake_invalid") from exc


def _close_details(exc: Any) -> tuple[int, str]:
    received = getattr(exc, "rcvd", None)
    return (int(getattr(received, "code", 1006) or 1006), str(getattr(received, "reason", "") or ""))


async def websockets_connect(url: str, headers: dict[str, str]) -> Connection:
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus, WebSocketException

    try:
        socket = await connect(url, additional_headers=headers, ping_interval=20, ping_timeout=40,
                               max_size=1024 * 1024, open_timeout=HANDSHAKE_TIMEOUT)
    except InvalidStatus as exc:
        status = getattr(getattr(exc, "response", None), "status_code", 0)
        raise ChannelClosedError(CLOSE_UNAUTHORIZED if status == 401 else 1006, "http_refused") from exc
    except (OSError, WebSocketException, TimeoutError) as exc:
        raise ChannelClosedError(1006, "unreachable") from exc
    return _WebsocketsConnection(socket)


def channel_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://"):] + CHANNEL_PATH
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://"):] + CHANNEL_PATH
    raise ValueError("base_url_invalid")


def _envelope(message_type: str, body: dict[str, Any], **extra: Any) -> str:
    return json.dumps({"v": PROTOCOL_VERSION, "type": message_type, "id": uuid.uuid4().hex, "ts": time.time(),
                       "body": body, **extra})
