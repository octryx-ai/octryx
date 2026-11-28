"""The content decision of a seat-route call: send it unchanged on the seat, or refuse."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ...agent_gateway.identity import GatewayIdentity
from ...content_routing.conversation_state import conversation_key
from ...content_routing.gateway_outcome import GatewayOutcome
from ...content_security.enforcement_inbound import InboundPlan, InboundRequest, enforce_inbound
from ...policy_engine.request_principal import load_seat_principal
from ...policy_engine.schema import ROUTE_GOVERNED, ROUTE_SEAT
from ...policy_engine.workspace_facts import load_workspace_classification_isolated
from ...prompt_catalog import prompt_set_scope
from ...prompt_catalog.out_of_turn import prompt_set_for
from .admission import InboundAdmission


# A subscription call is asked with route=seat for ModelAlias::"seat:<model>" (approved for nothing), a company call
# with route=governed.
async def seat_content_plan(
    db: AsyncSession, *, identity: GatewayIdentity, session: Session, body: Mapping[str, Any], model: str,
    headers: Mapping[str, str], outcome: GatewayOutcome, admitted: InboundAdmission | None = None,
) -> InboundPlan:
    if admitted is not None:
        project_admission = admitted.project_admission
        request = InboundRequest(
            body=body, outcome=outcome, route=ROUTE_GOVERNED, workspace_id=identity.workspace_id,
            conversation=conversation_key(headers), alias=admitted.entry.alias,
            approved_for=admitted.entry.approved_data_categories, admission=project_admission,
            principal=getattr(project_admission, "principal", None))
    else:
        principal = await load_seat_principal(identity.user.id, session_id=session.id,
                                              client=str((session.metadata_ or {}).get("client") or ""))
        request = InboundRequest(
            body=body, outcome=outcome, route=ROUTE_SEAT, workspace_id=identity.workspace_id,
            conversation=conversation_key(headers), alias=model.strip(), principal=principal,
            classification=await load_workspace_classification_isolated(identity.workspace_id, session.metadata_))
    with prompt_set_scope(await prompt_set_for(db, workspace_id=identity.workspace_id)):
        plan = await enforce_inbound(db, request)
    if plan.refusal is not None:
        from .secret_refusal_note import note_secret_refusal

        await note_secret_refusal(db, session.id, plan)
    return plan


__all__ = ["seat_content_plan"]
