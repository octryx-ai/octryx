"""Inbound channel webhook authentication: deny by default, per channel type."""

from .gate import AuthenticatedChannelWebhook, authenticate_channel_webhook, default_key_sources
from .refusals import (
    STATE_AUTH_NOT_CONFIGURED,
    STATE_PAYLOAD_INVALID,
    STATE_SIGNATURE_INVALID,
    STATE_SIGNING_KEYS_UNAVAILABLE,
    STATE_UNAUTHENTICATED,
    ChannelWebhookRefusedError,
)

__all__ = [
    "STATE_AUTH_NOT_CONFIGURED",
    "STATE_PAYLOAD_INVALID",
    "STATE_SIGNATURE_INVALID",
    "STATE_SIGNING_KEYS_UNAVAILABLE",
    "STATE_UNAUTHENTICATED",
    "AuthenticatedChannelWebhook",
    "ChannelWebhookRefusedError",
    "authenticate_channel_webhook",
    "default_key_sources",
]
