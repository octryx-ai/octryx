"""The inbound channel webhook gate: deny by default, channel-specific authentication first.

:func:`authenticate_channel_webhook` runs before the body is parsed and before any handler
work. It picks the scheme by the channel's plugin type, never by what the request says:

* ``msteams``: the Microsoft JWT (``microsoft_channel_token.py``) with the channel's
  ``app_id`` as audience, then bound to the parsed body (serviceUrl, sender profile, channel
  endorsement);
* ``slack``: the request signature (``slack_signature.py``) with the channel's
  ``signing_secret``;
* every other channel type has no inbound webhook scheme (they poll) and is refused with
  ``channel_webhook_auth_not_configured``.

A missing header, or a missing ``app_id`` / ``signing_secret``, is a refusal, never a skip.
The only way around authentication is the development exception
(``channel_webhook_dev_policy``), re-checked here on every request and logged every time.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...channel_webhook_dev_policy import channel_webhook_dev_bypass_active
from ...config import get_settings
from .microsoft_channel_token import (
    BOT_FRAMEWORK,
    GRAPH_CALLING,
    require_bound_to_payload,
    verify_microsoft_channel_token,
)
from .refusals import STATE_AUTH_NOT_CONFIGURED, STATE_PAYLOAD_INVALID, ChannelWebhookRefusedError
from .signing_keys import OpenIdSigningKeySource, SigningKeySource
from .slack_signature import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_slack_request

logger = logging.getLogger(__name__)

SCHEME_MICROSOFT_TOKEN = "microsoft_token"
SCHEME_SLACK_SIGNATURE = "slack_signature"
SCHEME_DEV_UNAUTHENTICATED = "dev_unauthenticated"
_SCHEMES = {"msteams": SCHEME_MICROSOFT_TOKEN, "slack": SCHEME_SLACK_SIGNATURE}

_key_sources: dict[str, SigningKeySource] = {}


def default_key_sources() -> Mapping[str, SigningKeySource]:
    """The process-wide cached key sources (one per Microsoft token profile)."""
    if not _key_sources:
        for profile in (BOT_FRAMEWORK, GRAPH_CALLING):
            _key_sources[profile.name] = OpenIdSigningKeySource(profile.openid_url, jwks_hosts=profile.jwks_hosts)
    return _key_sources


@dataclass(frozen=True, slots=True)
class AuthenticatedChannelWebhook:
    payload: dict[str, Any]
    scheme: str


def _parse_payload(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body) if body else {}
    except (ValueError, UnicodeDecodeError):
        raise ChannelWebhookRefusedError(STATE_PAYLOAD_INVALID, "body_not_json") from None
    if not isinstance(payload, dict):
        raise ChannelWebhookRefusedError(STATE_PAYLOAD_INVALID, "body_not_object")
    return payload


async def _authenticate(plugin: Any, scheme: str, headers: Mapping[str, str], body: bytes) -> dict[str, Any]:
    if scheme == SCHEME_MICROSOFT_TOKEN:
        app_id = str(getattr(plugin, "app_id", "") or "")
        if not app_id:
            raise ChannelWebhookRefusedError(STATE_AUTH_NOT_CONFIGURED, "teams_app_id_missing")
        verified = await verify_microsoft_channel_token(
            headers.get("authorization"), app_id=app_id, key_sources=default_key_sources()
        )
        payload = _parse_payload(body)
        require_bound_to_payload(verified, payload)
        return payload
    verify_slack_request(
        body,
        timestamp=headers.get(TIMESTAMP_HEADER.lower()),
        signature=headers.get(SIGNATURE_HEADER.lower()),
        signing_secret=str(getattr(plugin, "signing_secret", "") or ""),
    )
    return _parse_payload(body)


async def authenticate_channel_webhook(
    plugin: Any, *, channel_id: str, headers: Mapping[str, str], body: bytes
) -> AuthenticatedChannelWebhook:
    """The authenticated payload; raise :class:`ChannelWebhookRefusedError` for anything else.

    ``headers`` must be case-insensitive (Starlette ``Headers``) or lower-cased.
    """
    plugin_id = str(getattr(plugin, "plugin_id", "") or "")
    if channel_webhook_dev_bypass_active(get_settings()):
        logger.warning(
            "channel_webhook_dev_unauthenticated plugin=%s channel=%s (development exception is on)",
            plugin_id,
            channel_id,
        )
        return AuthenticatedChannelWebhook(_parse_payload(body), SCHEME_DEV_UNAUTHENTICATED)
    scheme = _SCHEMES.get(plugin_id)
    try:
        if scheme is None:
            raise ChannelWebhookRefusedError(STATE_AUTH_NOT_CONFIGURED, "channel_type_has_no_webhook_scheme")
        payload = await _authenticate(plugin, scheme, headers, body)
    except ChannelWebhookRefusedError as refused:
        logger.info(
            "channel_webhook_refused plugin=%s channel=%s state=%s reason=%s",
            plugin_id,
            channel_id,
            refused.state,
            refused.reason,
        )
        raise
    return AuthenticatedChannelWebhook(payload, scheme)


__all__ = [
    "SCHEME_DEV_UNAUTHENTICATED",
    "SCHEME_MICROSOFT_TOKEN",
    "SCHEME_SLACK_SIGNATURE",
    "AuthenticatedChannelWebhook",
    "authenticate_channel_webhook",
    "default_key_sources",
]
