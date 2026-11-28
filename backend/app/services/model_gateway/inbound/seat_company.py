"""A company model chosen in a seat session (``company/<alias>``): from the seat route on, a governed call."""

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
    # The bytes of the governed payload the content decision read (``enforcement_inbound.InboundPlan.payload``).
    payload: bytes = b""


def seat_principal_metadata(session: Session) -> dict[str, Any]:
    return {**(session.metadata_ or {}), "profile": SEAT_PROFILE}


# Authorization (the subscription login) stays behind, and anthropic-beta loses the subscription's oauth-* capability:
# it means nothing to the company gateway.
def governed_headers(headers: Mapping[str, str]) -> dict[str, str]:
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
    rerouted: bool = False,
) -> SeatCompanyCall | InboundRefusal:
    # A reroute is the Workspace's content handling, not the person's pick: the picker's opt-in does not apply.
    if not decision.governed_models and not rerouted:
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
