"""The explicit refusal states of an inbound channel webhook."""

from __future__ import annotations

STATE_UNAUTHENTICATED = "channel_webhook_unauthenticated"
STATE_SIGNATURE_INVALID = "channel_webhook_signature_invalid"
STATE_AUTH_NOT_CONFIGURED = "channel_webhook_auth_not_configured"
STATE_SIGNING_KEYS_UNAVAILABLE = "channel_webhook_signing_keys_unavailable"
STATE_PAYLOAD_INVALID = "channel_webhook_payload_invalid"

_HTTP_STATUS = {
    STATE_UNAUTHENTICATED: 401,
    STATE_SIGNATURE_INVALID: 401,
    STATE_AUTH_NOT_CONFIGURED: 403,
    STATE_SIGNING_KEYS_UNAVAILABLE: 503,
    STATE_PAYLOAD_INVALID: 400,
}


class ChannelWebhookRefusedError(Exception):
    """A webhook refused before any handler work; ``state`` is the explicit refusal code."""

    def __init__(self, state: str, reason: str = "") -> None:
        if state not in _HTTP_STATUS:
            raise ValueError("unknown channel webhook refusal state")
        super().__init__(state)
        self.state = state
        self.reason = reason or state

    @property
    def status_code(self) -> int:
        return _HTTP_STATUS[self.state]


__all__ = [
    "STATE_AUTH_NOT_CONFIGURED",
    "STATE_PAYLOAD_INVALID",
    "STATE_SIGNATURE_INVALID",
    "STATE_SIGNING_KEYS_UNAVAILABLE",
    "STATE_UNAUTHENTICATED",
    "ChannelWebhookRefusedError",
]
