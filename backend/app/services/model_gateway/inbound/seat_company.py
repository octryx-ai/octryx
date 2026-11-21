"""A company model chosen in a seat session.

A seat session's picker can offer the Workspace's company models as ``company/<alias>``
(``model_listing``) when the Workspace sets ``agent_gateway_policy.seat_allows_governed_models``
(default false). Such a call arrives on the seat route, which has already checked the seat credential, the
session and the seat policy. From there it is a governed call:

1. the opt-in, re-checked on every call (off: ``denied/seat_governed_models_not_allowed``);
2. admission of ``<alias>`` exactly as on the governed route (``admission.admit_inbound_call``, under the
   seat session's principal, so Cedar's ``call_model`` sees the chosen alias and the user);
3. the content decision on the governed payload (``governed_dispatch.governed_payload``, built before the scan),
   then ``governed_dispatch.dispatch_governed``: the daily and platform budgets, LiteLLM with the virtual key and
   exactly the scanned payload's bytes, the relay and the usage/transcript record. The record's evidence says
   ``client_profile: seat``.

The client's ``Authorization`` (the user's subscription login) never leaves the platform on this path: the
governed upstream forwards only ``anthropic-version`` and ``anthropic-beta``, and the subscription's OAuth
capability is removed from ``anthropic-beta`` (it means nothing to the company gateway). There is no fallback
in either direction: a subscription model never becomes a company call, and a company call never goes to the
subscription.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ...agent_gateway.contract import STATE_DENIED
from ...agent_gateway.identity import GatewayIdentity
from ...agent_gateway.presence import touch_presence
from ...agent_gateway.seat_policy import SeatDecision
from ...agent_gateway.seat_policy_keys import REASON_SEAT_GOVERNED_MODELS_NOT_ALLOWED
from ...policy_engine.request_principal import SEAT_PROFILE, policy_principal_scope
from .admission import InboundAdmission, admit_inbound_call
from .call_context import CLIENT_CONTEXT_HEADERS
from .model_listing import company_alias
from .refusals import REASON_BODY_INVALID, InboundRefusal, refusal
from .upstream import FORWARDED_REQUEST_HEADERS

CLIENT_PROFILE_SEAT = "seat"
_OAUTH_BETA_PREFIX = "oauth-"
GOVERNED_MODELS_HINT = (
    "This Workspace does not offer company models in seat sessions. Pick a subscription model with /model, "
    "or start the governed profile: octryx-claude --profile governed."
)


@dataclass(frozen=True, slots=True)
class SeatCompanyCall:
    identity: GatewayIdentity
    session_id: str
    body: dict[str, Any]
    admitted: InboundAdmission
    # The headers the governed path reads (``governed_headers``), lower-case.
    headers: Mapping[str, str]
    # The bytes of the governed payload the content decision read (``gateway_plan.InboundPlan.payload``).
    payload: bytes = b""


def seat_principal_metadata(session: Session) -> dict[str, Any]:
    """The seat session's metadata for its Cedar principal: always profile ``seat`` (the row says
    ``gateway_profile``; the principal reads ``profile`` and would default to governed)."""
    return {**(session.metadata_ or {}), "profile": SEAT_PROFILE}


def governed_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """What the governed path reads: Claude Code's correlation headers (for the transcript) and the two headers
    the upstream forwards, ``anthropic-version`` and ``anthropic-beta`` without the subscription's ``oauth-*``
    capability. ``Authorization`` and every other header stay behind."""
    kept = {name: str(headers.get(name) or "") for name in (*FORWARDED_REQUEST_HEADERS, *CLIENT_CONTEXT_HEADERS)}
    betas = [item.strip() for item in kept.get("anthropic-beta", "").split(",")]
    kept["anthropic-beta"] = ",".join(item for item in betas if item and not item.startswith(_OAUTH_BETA_PREFIX))
    return {name: value for name, value in kept.items() if value}


async def admit_seat_company_call(
    db: AsyncSession,
    *,
    identity: GatewayIdentity,
    session: Session,
    decision: SeatDecision,
    body: dict[str, Any],
    headers: Mapping[str, str],
) -> SeatCompanyCall | InboundRefusal:
    """Steps 1 and 2 for a ``company/<alias>`` call on the seat route."""
    if not decision.governed_models:
        return refusal(STATE_DENIED, REASON_SEAT_GOVERNED_MODELS_NOT_ALLOWED, http_status=403,
                       hint=GOVERNED_MODELS_HINT)
    model = body["model"].strip()
    alias = company_alias(model)
    if not alias:
        return refusal(STATE_DENIED, REASON_BODY_INVALID, http_status=400)
    async with policy_principal_scope(identity.user.id, session_id=session.id,
                                      metadata=seat_principal_metadata(session)):
        admitted = await admit_inbound_call(
            db, workspace_id=identity.workspace_id, alias=alias, declares_tools=bool(body.get("tools"))
        )
    if isinstance(admitted, InboundRefusal):
        return admitted
    await touch_presence(db, identity.session_key, model=model)
    evidence = {**admitted.evidence, "client_profile": CLIENT_PROFILE_SEAT}
    return SeatCompanyCall(identity, session.id, body, replace(admitted, evidence=evidence), governed_headers(headers))


__all__ = [
    "CLIENT_PROFILE_SEAT",
    "GOVERNED_MODELS_HINT",
    "SeatCompanyCall",
    "admit_seat_company_call",
    "governed_headers",
    "seat_principal_metadata",
]
