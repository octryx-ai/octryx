"""Slack request signature verification."""

from __future__ import annotations

import hashlib
import hmac
import time

from .refusals import (
    STATE_AUTH_NOT_CONFIGURED,
    STATE_SIGNATURE_INVALID,
    STATE_UNAUTHENTICATED,
    ChannelWebhookRefusedError,
)

REPLAY_WINDOW_SECONDS = 300
SIGNATURE_HEADER = "X-Slack-Signature"
TIMESTAMP_HEADER = "X-Slack-Request-Timestamp"
_VERSION = "v0"


def slack_signature(signing_secret: str, timestamp: str, body: bytes) -> str:
    base = f"{_VERSION}:{timestamp}:".encode() + body
    return f"{_VERSION}=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()


def verify_slack_request(
    body: bytes,
    *,
    timestamp: str | None,
    signature: str | None,
    signing_secret: str,
    now: float | None = None,
) -> None:
    if not signing_secret:
        raise ChannelWebhookRefusedError(STATE_AUTH_NOT_CONFIGURED, "slack_signing_secret_missing")
    if not timestamp or not signature:
        raise ChannelWebhookRefusedError(STATE_UNAUTHENTICATED, "slack_signature_headers_missing")
    try:
        sent_at = int(timestamp)
    except ValueError:
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "slack_timestamp_malformed") from None
    current = time.time() if now is None else now
    if abs(current - sent_at) > REPLAY_WINDOW_SECONDS:
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "slack_timestamp_stale")
    expected = slack_signature(signing_secret, timestamp, body)
    if not hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8")):
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "slack_signature_mismatch")


__all__ = [
    "REPLAY_WINDOW_SECONDS",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "slack_signature",
    "verify_slack_request",
]
