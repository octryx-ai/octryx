"""The per-call token of the Teams call audio WebSocket."""

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
    project_id: str
    expires_at: float


_issued: dict[str, _IssuedToken] = {}


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _prune(now: float) -> None:
    for call_id in [key for key, issued in _issued.items() if issued.expires_at <= now]:
        _issued.pop(call_id, None)


def issue_call_audio_token(call_id: str, *, channel_id: str, project_id: str) -> str:
    now = time.monotonic()
    _prune(now)
    token = secrets.token_urlsafe(32)
    _issued[str(call_id)] = _IssuedToken(_digest(token), str(channel_id), str(project_id), now + TOKEN_TTL_SECONDS)
    return token


def verify_call_audio_token(call_id: str, *, channel_id: str, project_id: str, token: str | None) -> str | None:
    if not token:
        return STATE_TOKEN_MISSING
    now = time.monotonic()
    _prune(now)
    issued = _issued.get(str(call_id))
    # The digest comparison runs whenever a token was issued, so timing does not tell a wrong
    # token from a wrong channel.
    matches = issued is not None and hmac.compare_digest(issued.digest, _digest(token))
    if not matches or issued is None or (issued.channel_id, issued.project_id) != (str(channel_id), str(project_id)):
        return STATE_TOKEN_INVALID
    return None


def consume_call_audio_token(call_id: str, *, channel_id: str, project_id: str, token: str | None) -> str | None:
    refusal = verify_call_audio_token(call_id, channel_id=channel_id, project_id=project_id, token=token)
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
