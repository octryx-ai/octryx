"""Verification of the JWT Microsoft sends with every Teams channel webhook.

Two senders post to a Teams channel's webhook, each signing with its own published keys:

* **Bot Framework** (chat activities, ``callStateChange``): keys from the Bot Framework OpenID
  metadata, issuer ``https://api.botframework.com``. The token's ``serviceUrl`` claim must equal
  the activity's ``serviceUrl``, and a key that carries ``endorsements`` must endorse the
  activity's ``channelId``.
* **Graph calling** (``commsNotifications`` sent to the call's ``callbackUri``): keys from the
  Skype OpenID metadata, issuer ``https://graph.microsoft.com`` or
  ``https://api.botframework.com``.

For both: ``Authorization: Bearer <JWT>``, RS256 only, the audience is the channel's
``app_id``, ``exp`` is required and checked, ``nbf`` when present, with
:data:`CLOCK_SKEW_SECONDS` leeway. The key id decides the profile: a token verifies only with a
key of the source that published it, so a Bot Framework token cannot pass as a Graph calling
notification or the other way round. :func:`verify_microsoft_channel_token` authenticates the
header before the body is parsed; :func:`require_bound_to_payload` then binds the verified
claims to the parsed body before any handler runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jwt

from .refusals import (
    STATE_SIGNATURE_INVALID,
    STATE_SIGNING_KEYS_UNAVAILABLE,
    STATE_UNAUTHENTICATED,
    ChannelWebhookRefusedError,
)
from .signing_keys import SigningKeySource, SigningKeysUnavailableError

CLOCK_SKEW_SECONDS = 300
_ALGORITHM = "RS256"
GRAPH_COMMS_NOTIFICATIONS = "#microsoft.graph.commsNotifications"


@dataclass(frozen=True, slots=True)
class TokenProfile:
    name: str
    openid_url: str
    issuers: tuple[str, ...]
    jwks_hosts: frozenset[str]


BOT_FRAMEWORK = TokenProfile(
    name="bot_framework",
    openid_url="https://login.botframework.com/v1/.well-known/openidconfiguration",
    issuers=("https://api.botframework.com",),
    jwks_hosts=frozenset({"login.botframework.com"}),
)
GRAPH_CALLING = TokenProfile(
    name="graph_calling",
    openid_url="https://api.aps.skype.com/v1/.well-known/OpenIdConfiguration",
    issuers=("https://graph.microsoft.com", "https://api.botframework.com"),
    jwks_hosts=frozenset({"api.aps.skype.com"}),
)
PROFILES: tuple[TokenProfile, ...] = (BOT_FRAMEWORK, GRAPH_CALLING)


@dataclass(frozen=True, slots=True)
class VerifiedMicrosoftToken:
    profile: str
    claims: dict[str, Any]
    endorsements: tuple[str, ...] | None


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = str(authorization or "").strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ChannelWebhookRefusedError(STATE_UNAUTHENTICATED, "bearer_token_missing")
    return token.strip()


async def _find_key(kid: str, key_sources: Mapping[str, SigningKeySource]) -> tuple[TokenProfile, dict[str, Any]]:
    try:
        for refresh in (False, True):
            for profile in PROFILES:
                source = key_sources.get(profile.name)
                if source is None:
                    continue
                for key in await source.keys(refresh=refresh):
                    if key.get("kid") == kid:
                        return profile, key
    except SigningKeysUnavailableError as unavailable:
        raise ChannelWebhookRefusedError(STATE_SIGNING_KEYS_UNAVAILABLE, str(unavailable)) from None
    raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "unknown_signing_key")


_DECODE_REASONS: tuple[tuple[type[Exception], str], ...] = (
    (jwt.ExpiredSignatureError, "token_expired"),
    (jwt.ImmatureSignatureError, "token_not_yet_valid"),
    (jwt.InvalidAudienceError, "token_audience_invalid"),
    (jwt.InvalidIssuerError, "token_issuer_invalid"),
    (jwt.MissingRequiredClaimError, "token_claim_missing"),
    (jwt.InvalidSignatureError, "token_signature_invalid"),
)


async def verify_microsoft_channel_token(
    authorization: str | None, *, app_id: str, key_sources: Mapping[str, SigningKeySource]
) -> VerifiedMicrosoftToken:
    """The verified claims of the request's bearer token; raise ``ChannelWebhookRefusedError`` otherwise."""
    token = _bearer_token(authorization)
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "token_malformed") from None
    if header.get("alg") != _ALGORITHM:
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "token_algorithm_not_allowed")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "token_kid_missing")
    profile, jwk = await _find_key(kid, key_sources)
    try:
        signing_key = jwt.PyJWK(jwk, algorithm=_ALGORITHM).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=[_ALGORITHM],
            audience=app_id,
            issuer=profile.issuers,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as invalid:
        reason = next((code for kind, code in _DECODE_REASONS if isinstance(invalid, kind)), "token_invalid")
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, reason) from None
    endorsements = jwk.get("endorsements")
    return VerifiedMicrosoftToken(
        profile=profile.name,
        claims=claims,
        endorsements=tuple(str(item) for item in endorsements) if isinstance(endorsements, list) else None,
    )


def _normalized_service_url(value: object) -> str:
    return str(value or "").strip().rstrip("/").lower()


def require_bound_to_payload(verified: VerifiedMicrosoftToken, payload: dict[str, Any]) -> None:
    """The verified token must belong to this body: its sender profile, serviceUrl and channel."""
    is_graph_notification = payload.get("@odata.type") == GRAPH_COMMS_NOTIFICATIONS
    if verified.profile == GRAPH_CALLING.name:
        if not is_graph_notification:
            raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "token_profile_payload_mismatch")
        return
    if is_graph_notification:
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "token_profile_payload_mismatch")
    claimed = _normalized_service_url(verified.claims.get("serviceUrl") or verified.claims.get("serviceurl"))
    if not claimed or claimed != _normalized_service_url(payload.get("serviceUrl")):
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "token_service_url_mismatch")
    if verified.endorsements is not None and str(payload.get("channelId") or "") not in verified.endorsements:
        raise ChannelWebhookRefusedError(STATE_SIGNATURE_INVALID, "token_channel_not_endorsed")


__all__ = [
    "BOT_FRAMEWORK",
    "CLOCK_SKEW_SECONDS",
    "GRAPH_CALLING",
    "GRAPH_COMMS_NOTIFICATIONS",
    "PROFILES",
    "TokenProfile",
    "VerifiedMicrosoftToken",
    "require_bound_to_payload",
    "verify_microsoft_channel_token",
]
