"""The explicit refusal states of an inbound channel webhook.

* ``channel_webhook_unauthenticated`` (401): the channel's authentication header is missing.
* ``channel_webhook_signature_invalid`` (401): the token or signature does not verify: wrong
  signature, issuer or audience, expired, stale timestamp, unknown signing key, or a token that
  is not bound to the request it came with.
* ``channel_webhook_auth_not_configured`` (403): the channel type has no inbound authentication
  scheme, or the channel lacks the setting its scheme needs (Teams ``app_id``, Slack
  ``signing_secret``).
* ``channel_webhook_signing_keys_unavailable`` (503): the published signing keys could not be
  fetched; nothing is accepted without them.
* ``channel_webhook_payload_invalid`` (400): an authenticated body that is not a JSON object.

``reason`` is a fixed, input-free token for the log only; tokens, signatures and bodies are never
logged or echoed.
"""

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
