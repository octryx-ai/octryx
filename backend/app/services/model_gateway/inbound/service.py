"""The inbound Anthropic Messages gateway for external coding clients."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ...agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ...agent_gateway.identity import GatewayIdentity, GatewayRefusal, resolve_gateway_identity
from ...agent_gateway.presence import touch_presence
from ...agent_gateway.sessions import get_or_create_gateway_session
from ...content_detection.request_examination import strict_json, utf8_clean
from ...content_routing.conversation_state import conversation_key
from ...content_routing.decision import REASON_SCAN_UNFINISHED
from ...content_routing.gateway import UNFINISHED_HINT
from ...content_routing.gateway_outcome import STAGE_BODY, gateway_outcome, recorded
from ...content_security.enforcement_inbound import InboundPlan, InboundRequest, enforce_inbound
from ...policy_engine.request_principal import policy_principal_scope
from ...policy_engine.schema import ROUTE_GOVERNED
from ...prompt_catalog import prompt_set_scope
from ...prompt_catalog.out_of_turn import prompt_set_for
from .admission import InboundAdmission, admit_inbound_call
from .call_context import ErrorRenderer, render_refusal
from .content_reroute import planned
from .governed_dispatch import count_tokens_governed, dispatch_governed, governed_payload
from .refusals import (
    REASON_BODY_INVALID,
    REASON_BODY_TOO_LARGE,
    InboundRefusal,
    anthropic_error_response,
    refusal,
)

MAX_REQUEST_BODY_BYTES = 16 * 1024 * 1024

logger = logging.getLogger(__name__)


def is_messages_body(body: Any) -> bool:
    return isinstance(body, dict) and isinstance(body.get("messages"), list)


async def _read_raw(request: Request) -> bytes | None:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return None
    return bytes(raw)


# Bounded in size and by the content deadline that starts at handler entry; a body that is not strict JSON or valid
# UTF-8 is request_body_invalid before anything else reads it, recorded at stage body.
async def _read_body(
    request: Request, *, valid: Callable[[Any], bool] = is_messages_body, invalid_hint: str = ""
) -> dict[str, Any] | InboundRefusal:
    outcome = gateway_outcome(request)
    declared = request.headers.get("content-length", "")
    too_large = refusal(STATE_DENIED, REASON_BODY_TOO_LARGE, http_status=413)
    if declared.isdigit() and int(declared) > MAX_REQUEST_BODY_BYTES:
        return outcome.refuse(too_large, STAGE_BODY)
    try:
        async with asyncio.timeout(max(outcome.budget.deadline - time.monotonic(), 0)):
            raw = await _read_raw(request)
    except TimeoutError:
        return outcome.refuse(refusal(STATE_DENIED, REASON_SCAN_UNFINISHED, http_status=400, hint=UNFINISHED_HINT),
                              STAGE_BODY, fixed="unfinished")
    if raw is None:
        return outcome.refuse(too_large, STAGE_BODY)
    try:
        body = strict_json(raw.decode("utf-8"))
    except ValueError:  # invalid UTF-8, invalid JSON, a repeated key, too deep, not finite
        body = None
    if not utf8_clean(body):
        body = None
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("model"), str)
        or not body["model"].strip()
        or not valid(body)
    ):
        return outcome.refuse(refusal(STATE_DENIED, REASON_BODY_INVALID, http_status=400, hint=invalid_hint),
                              STAGE_BODY, fixed="unreadable")
    return body


async def content_plan(
    db: AsyncSession, *, request: Request, body: dict[str, Any], identity: GatewayIdentity,
    admitted: InboundAdmission,
) -> InboundPlan:
    project_admission = admitted.project_admission
    inbound = InboundRequest(
        body=body, outcome=gateway_outcome(request), route=ROUTE_GOVERNED, workspace_id=identity.workspace_id,
        conversation=conversation_key(request.headers), alias=admitted.entry.alias,
        approved_for=admitted.entry.approved_data_categories, admission=project_admission,
        principal=getattr(project_admission, "principal", None),
    )
    with prompt_set_scope(await prompt_set_for(db, workspace_id=identity.workspace_id)):
        plan = await enforce_inbound(db, inbound)
    if plan.refusal is not None:
        from .secret_refusal_note import note_secret_refusal

        await note_secret_refusal(db, gateway_outcome(request).session_id, plan)
    return plan


async def governed_plan(
    db: AsyncSession, *, request: Request, identity: GatewayIdentity, session_id: str, admitted: InboundAdmission,
    build: Callable[[InboundAdmission], dict[str, Any]],
) -> tuple[InboundPlan, InboundAdmission]:
    async def plan_for(target: InboundAdmission) -> InboundPlan:
        return await content_plan(db, request=request, body=build(target), identity=identity, admitted=target)

    async def admit(alias: str) -> InboundAdmission | InboundRefusal:
        session = await db.get(Session, session_id)
        async with policy_principal_scope(identity.user.id, session_id=session_id,
                                          metadata=session.metadata_ if session is not None else None):
            return await admit_inbound_call(db, workspace_id=identity.workspace_id, alias=alias,
                                            declares_tools=bool(build(admitted).get("tools")))

    return await planned(plan_for, admit, admitted, gateway_outcome(request))


async def admitted_request(
    request: Request, db: AsyncSession, *, render: ErrorRenderer = anthropic_error_response,
    valid: Callable[[Any], bool] = is_messages_body, invalid_hint: str = "",
) -> tuple[GatewayIdentity, str, dict[str, Any], InboundAdmission] | Response:
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return render_refusal(identity, render)
    session = await get_or_create_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return render_refusal(session, render)
    gateway_outcome(request).bind(route=ROUTE_GOVERNED, workspace_id=identity.workspace_id, session_id=session.id,
                                  user_id=identity.user.id)
    body = await _read_body(request, valid=valid, invalid_hint=invalid_hint)
    if isinstance(body, InboundRefusal):
        return render_refusal(body, render)
    from .run_limits import run_limited_body

    body = await run_limited_body(db, session.id, body)  # the run's model and budget, whatever the session asks
    if isinstance(body, InboundRefusal):
        return render_refusal(body, render)
    # Presence of the session; committed with the shadow session below.
    await touch_presence(db, identity.session_key, model=body["model"].strip())
    # The admission is built for this user and session (its later re-checks decide for them too).
    async with policy_principal_scope(identity.user.id, session_id=session.id, metadata=session.metadata_):
        admitted = await admit_inbound_call(
            db,
            workspace_id=identity.workspace_id,
            alias=body["model"].strip(),
            declares_tools=bool(body.get("tools")),
        )
    if isinstance(admitted, InboundRefusal):
        return render_refusal(admitted, render)
    from ...workflow_runs.octryx.agent_view import phase_agent_model_refusal

    served = getattr(admitted.entry, "served_model_ids", frozenset()) or frozenset()
    agent_refused = await phase_agent_model_refusal(
        db, session.id, sorted(served), labels=(admitted.entry.model_group, body["model"]))
    if agent_refused:  # the phase agent's coding preference, never a silent weak model
        return render_refusal(refusal(STATE_NEEDS_CONFIGURATION, agent_refused), render)
    from ...workflow_runs.octryx.run_guard import device_loop_refusal

    looping = await device_loop_refusal(db, session.id)
    if looping:  # a phase turn running in circles ends here, not at the launcher's job limit
        return render_refusal(refusal(STATE_DENIED, looping, http_status=403,
                                hint="The workflow run paused this turn: the agent was looping. End the turn."),
                        render)
    return identity, session.id, body, admitted


def context_size(body: Mapping[str, Any]) -> dict[str, Any]:
    # A run turn's base context must stay under 10k tokens, so it is measured.
    def size(value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False)) if value is not None else 0

    offered = body.get("tools")
    tools = [tool for tool in offered if isinstance(tool, dict)] if isinstance(offered, list) else []
    sized = sorted(((str(tool.get("name") or ""), size(tool)) for tool in tools), key=lambda item: -item[1])
    return {"system_chars": size(body.get("system")), "tools": len(tools), "tool_chars": sum(n for _, n in sized),
            "largest_tools": sized[:8], "tool_names": [name for name, _ in sized][:200],
            "messages": len(messages) if isinstance(messages := body.get("messages"), list) else 0,
            "message_chars": size(body.get("messages"))}


def log_context_size(body: Mapping[str, Any], *, session_id: str) -> None:
    logger.info("gateway.context_size %s", json.dumps({"session_id": session_id, "model": body.get("model"),
                                                       **context_size(body)}, ensure_ascii=False))


@recorded
async def handle_messages(request: Request, db: AsyncSession) -> Response:
    resolved = await admitted_request(request, db)
    if isinstance(resolved, Response):
        return resolved
    identity, session_id, body, admitted = resolved
    log_context_size(body, session_id=session_id)
    plan, admitted = await governed_plan(db, request=request, identity=identity, session_id=session_id,
                                         admitted=admitted, build=lambda target: governed_payload(body, target))
    if plan.refusal is not None:
        return render_refusal(plan.refusal)
    return await dispatch_governed(db, headers=request.headers, identity=identity, session_id=session_id,
                                   body=body, payload=plan.payload, admitted=admitted,
                                   outcome=gateway_outcome(request))


@recorded
async def handle_count_tokens(request: Request, db: AsyncSession) -> Response:
    resolved = await admitted_request(request, db)
    if isinstance(resolved, Response):
        return resolved
    identity, session_id, body, admitted = resolved
    plan, admitted = await governed_plan(db, request=request, identity=identity, session_id=session_id,
                                         admitted=admitted, build=lambda target: governed_payload(body, target))
    if plan.refusal is not None:
        return render_refusal(plan.refusal)
    return await count_tokens_governed(db, headers=request.headers, payload=plan.payload, admitted=admitted,
                                       outcome=gateway_outcome(request))


__all__ = [
    "MAX_REQUEST_BODY_BYTES",
    "admitted_request",
    "content_plan",
    "governed_plan",
    "handle_count_tokens",
    "handle_messages",
]
