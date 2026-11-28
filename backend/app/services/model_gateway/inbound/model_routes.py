"""GET /v1/models on the governed and the seat route: what Claude Code's /model picker offers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.contract import GATEWAY_CLIENT, REASON_SESSION_NOT_FOUND, STATE_DENIED
from ...agent_gateway.identity import GatewayIdentity, GatewayRefusal, resolve_gateway_identity
from ...agent_gateway.presence import session_key_hash
from ...agent_gateway.seat_policy import SeatDecision
from ...agent_gateway.sessions import find_gateway_session
from ...policy_engine.request_principal import SEAT_PROFILE, policy_principal_scope
from ..litellm.alias_catalog import AliasEntry
from .admission import admitted_tool_aliases
from .model_listing import REASON_LIST_QUERY_INVALID, PickerModel, company_models, list_page, seat_models
from .refusals import InboundRefusal, anthropic_error_response, refusal
from .seat import seat_context
from .seat_company import seat_principal_metadata


def _page(models: list[PickerModel], request: Request) -> Response:
    page = list_page(models, request.query_params)
    if page is None:
        return anthropic_error_response(refusal(STATE_DENIED, REASON_LIST_QUERY_INVALID, http_status=400))
    return JSONResponse(page)


async def governed_models(
    request: Request, db: AsyncSession, *, render: Callable[[InboundRefusal], Response] = anthropic_error_response
) -> list[PickerModel] | Response:
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return render(refusal(identity.state, identity.reason, http_status=identity.http_status))
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        if session.reason != REASON_SESSION_NOT_FOUND:
            return render(refusal(session.state, session.reason, http_status=session.http_status))
        session_id, metadata = f"launch:{session_key_hash(identity.session_key)}", {"client": GATEWAY_CLIENT}
    else:
        session_id, metadata = session.id, session.metadata_
    async with policy_principal_scope(identity.user.id, session_id=session_id, metadata=metadata):
        entries = await admitted_tool_aliases(db, identity.workspace_id)
    return company_models(entries)


async def handle_list_models(request: Request, db: AsyncSession) -> Response:
    models = await governed_models(request, db)
    return models if isinstance(models, Response) else _page(models, request)


async def handle_seat_list_models(request: Request, db: AsyncSession) -> Response:
    context = await seat_context(request, db)
    if isinstance(context, Response):
        return context
    identity, session, decision = context
    entries = ()
    if decision.governed_models:
        async with policy_principal_scope(identity.user.id, session_id=session.id,
                                          metadata=seat_principal_metadata(session)):
            entries = await admitted_tool_aliases(db, identity.workspace_id)
    return _page(seat_models(decision.models, entries), request)


# Each list is decided for a launch with that profile (Cedar's call_model tells the profiles apart); the seat list is
# empty when the Workspace refuses seat sessions.
async def launcher_picker(db: AsyncSession, identity: GatewayIdentity, seat: SeatDecision) -> dict[str, Any]:
    launch = f"launch:{session_key_hash(identity.session_key)}"
    async with policy_principal_scope(identity.user.id, session_id=launch, metadata={"client": GATEWAY_CLIENT}):
        governed = company_models(await admitted_tool_aliases(db, identity.workspace_id))
    seat_rows: list[PickerModel] = []
    if seat.allowed:
        entries: tuple[AliasEntry, ...] = ()
        if seat.governed_models:
            async with policy_principal_scope(identity.user.id, session_id=launch,
                                              metadata={"profile": SEAT_PROFILE, "client": GATEWAY_CLIENT}):
                entries = await admitted_tool_aliases(db, identity.workspace_id)
        seat_rows = seat_models(seat.models, entries)
    return {
        "governed": [model.row() for model in governed],
        "seat": [model.row() for model in seat_rows],
        "seat_allows_governed_models": seat.governed_models,
    }


__all__ = ["governed_models", "handle_list_models", "handle_seat_list_models", "launcher_picker"]
