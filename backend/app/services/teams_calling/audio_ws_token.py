"""The per-call token of the Teams call audio WebSocket.

The audio WebSocket (``/api/v1/teams/calls/{call_id}/audio/ws``) streams a caller's speech into
an agent turn; the channel context in its query string alone is guessable. When the platform
accepts a call (``TeamsPlugin._build_calling_response``) it issues a token for that call and puts
it into the ``audioWebSocketUri`` it hands to the media bridge:

* 32 random bytes (``secrets.token_urlsafe``), bound to the call id and the channel id;
* short-lived (:data:`TOKEN_TTL_SECONDS`) and single-use: the first valid connect consumes it,
  so a replay is refused;
* only its SHA-256 digest is kept, compared in constant time; the token is never logged.

:func:`consume_call_audio_token` returns ``None`` when the connect may proceed, else the refusal
state (``call_audio_token_missing`` / ``call_audio_token_invalid``); the route refuses before it
accepts the WebSocket, so no audio is read.

The store is process-local, like the rest of the call pipeline's state (``call_session_state``):
the WebSocket must reach the process that accepted the call.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

TOKEN_TTL_SECONDS = 120.0
STATE_TOKEN_MISSING = "call_audio_token_missing"
STATE_TOKEN_INVALID = "call_audio_token_invalid"


@dataclass(frozen=True, slots=True)
class _IssuedToken:
    digest: bytes
    channel_id: str
    expires_at: float


_issued: dict[str, _IssuedToken] = {}


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _prune(now: float) -> None:
    for call_id in [key for key, issued in _issued.items() if issued.expires_at <= now]:
        _issued.pop(call_id, None)


def issue_call_audio_token(call_id: str, *, channel_id: str) -> str:
    """A new token for ``call_id`` on ``channel_id``; replaces any earlier token of that call."""
    now = time.monotonic()
    _prune(now)
    token = secrets.token_urlsafe(32)
    _issued[str(call_id)] = _IssuedToken(_digest(token), str(channel_id), now + TOKEN_TTL_SECONDS)
    return token


def verify_call_audio_token(call_id: str, *, channel_id: str, token: str | None) -> str | None:
    """``None`` when ``token`` is ``call_id``'s valid, unexpired, unused token (left unused); else the state.

    The ``/incoming-call`` callback authenticates with it; only the WebSocket
    consumes it.
    """
    if not token:
        return STATE_TOKEN_MISSING
    now = time.monotonic()
    _prune(now)
    issued = _issued.get(str(call_id))
    # The digest comparison runs whenever a token was issued, so timing does not tell a wrong
    # token from a wrong channel.
    matches = issued is not None and hmac.compare_digest(issued.digest, _digest(token))
    if not matches or issued is None or issued.channel_id != str(channel_id):
        return STATE_TOKEN_INVALID
    return None


def consume_call_audio_token(call_id: str, *, channel_id: str, token: str | None) -> str | None:
    """``None`` when ``token`` is ``call_id``'s valid, unexpired, unused token (now consumed); else the state."""
    refusal = verify_call_audio_token(call_id, channel_id=channel_id, token=token)
    if refusal is None:
        _issued.pop(str(call_id), None)
    return refusal


def revoke_call_audio_token(call_id: str) -> None:
    _issued.pop(str(call_id), None)


__all__ = [
    "STATE_TOKEN_INVALID",
    "STATE_TOKEN_MISSING",
    "TOKEN_TTL_SECONDS",
    "consume_call_audio_token",
    "issue_call_audio_token",
    "revoke_call_audio_token",
    "verify_call_audio_token",
]
