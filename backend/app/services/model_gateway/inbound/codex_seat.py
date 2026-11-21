"""The Codex seat route: a ``seat`` session's Codex calls to ChatGPT with the person's own ChatGPT login.

The launcher configures Codex with a provider (``requires_openai_auth = true``) whose ``base_url`` is
``<platform>/api/v1/model-gateway/openai/seat``, so Codex posts ``{base_url}/responses`` with its ChatGPT token as
``Authorization``. One call runs, in this order, and stops at the first explicit refusal (an OpenAI-shaped error
with a fixed reason), exactly like the Claude seat route (``seat``):

1. identity from the session-bound seat credential (``agent_gateway/seat_credential``), re-checked on every call;
   then the existing session;
2. the Workspace's Codex seat policy, re-checked on every call (``codex_seat_mode``, ``requires_governed_routing``,
   the classification matrix: ``confidential`` and up or unresolved forbid); no silent fallback to the governed
   route. The Workspace must allow the Codex engine (``engine_not_allowed_in_workspace``);
3. the bounded Responses body; the upstream configuration; the client's ``Authorization`` must be present;
4. the gateway's content decision over the body that is forwarded (``seat_content_plan``: the fixed rules, the
   Workspace's content handling — ``secrets`` and ``credential_assignment``, ``refuse`` or ``report`` —, Cedar with
   ``route=seat``): it refuses or the body goes on unchanged. The Anthropic-shaped view (``openai_view``) is only the
   transcript;
5. the call goes to ChatGPT's ``/backend-api/codex/responses`` only (``codex_seat_upstream``) with only the
   allowlisted request headers. Namespace tools are not flattened (ChatGPT's backend supports them). No platform
   budget is spent and no LiteLLM is used.

``seat_traffic`` (platform switch, ``agent_gateway.seat_traffic``) decides where the call leaves: ``gateway`` is this
route; ``device`` (default) refuses it (``codex_seat_traffic_device``) and the launcher's loopback seat proxy sends
the call itself after the same steps 1-4 admitted it (:func:`admit_codex_seat`, ``codex_seat_device``).

The upstream answer goes back **unchanged** (status, body, allowlisted headers), also for errors; it is observed
(``codex_seat_observer``) and usage and transcript are recorded after the response (``seat_transcript``, cost 0).
ChatGPT's rate-limit windows (``x-codex-primary-*`` = 5 h, ``x-codex-secondary-*`` = 7 d) go into the session's
presence allowance (``agent_gateway.allowance.parse_codex_allowance``), the fields the Claude seat fills.
The ChatGPT token is never stored, logged, audited or put into an error or the transcript.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_gateway.allowance import parse_codex_allowance
from ...agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION, STATE_UNAUTHORIZED
from ...agent_gateway.engine_keys import ENGINE_CODEX, REASON_ENGINE_NOT_ALLOWED
from ...agent_gateway.engine_policy import effective_engine
from ...agent_gateway.identity import GatewayIdentity, GatewayRefusal
from ...agent_gateway.presence import record_allowance, touch_presence
from ...agent_gateway.seat_credential import REASON_SEAT_SESSION_EXPIRED, resolve_seat_identity
from ...agent_gateway.seat_policy import workspace_seat_decision
from ...agent_gateway.seat_policy_keys import REASON_SEAT_MODEL_NOT_ALLOWED
from ...agent_gateway.seat_traffic import (
    REASON_TRAFFIC_DEVICE,
    REASON_TRAFFIC_GATEWAY,
    SEAT_TRAFFIC_DEVICE,
    SEAT_TRAFFIC_GATEWAY,
    seat_traffic,
)
from ...agent_gateway.sessions import find_gateway_session
from ...content_routing.gateway_outcome import gateway_outcome, recorded
from ...content_routing.gateway_plan import HEADER_OBLIGATION
from ...policy_engine.request_principal import load_seat_principal
from ...policy_engine.schema import ROUTE_SEAT
from .anthropic_stream import Observation
from .call_context import client_context
from .codex_seat_relay import buffered_codex_answer, send_codex_seat, streamed_codex_answer
from .codex_seat_upstream import build_codex_seat_client, codex_seat_response_headers, codex_seat_upstream_problem
from .openai_service import BODY_INVALID_HINT, CODEX_CONTEXT_HEADERS
from .openai_view import anthropic_view, is_responses_body
from .refusals import InboundRefusal, openai_error_response, refusal
from .run_limits import run_limited_body
from .seat import REASON_SEAT_AUTHORIZATION_MISSING
from .seat_content import seat_content_plan
from .seat_transcript import SeatCallRecord
from .service import _read_body

CODEX_SEAT_PROVIDER = "openai_codex_seat"
CODEX_SEAT_DISPATCH_OWNER = "model_gateway_inbound_openai_codex_seat"
LOGIN_HINT = "Sign in with your own ChatGPT account in this Codex profile: run codex login."
EXPIRED_HINT = "The seat session ended. Start a new Codex seat session."
_ENGINE_HINT = "Codex is not allowed in this Workspace; a Workspace admin can allow it under the coding engines."
_TRAFFIC_HINTS = {
    SEAT_TRAFFIC_DEVICE: "This platform sends Codex seat calls from your device. Update the launcher (octryx update) "
                         "and start the session again.",
    SEAT_TRAFFIC_GATEWAY: "This platform relays Codex seat calls itself; start the session again so the launcher "
                          "uses the platform's seat route.",
}


def codex_seat_refused(item: InboundRefusal | GatewayRefusal) -> Response:
    if isinstance(item, GatewayRefusal):
        hint = EXPIRED_HINT if item.reason == REASON_SEAT_SESSION_EXPIRED else ""
        item = refusal(item.state, item.reason, http_status=item.http_status, hint=hint)
    return openai_error_response(item)


async def _codex_seat_context(request: Request, db: AsyncSession) -> tuple[GatewayIdentity, Any, Any] | Response:
    """Steps 1 and 2: the seat identity, its session, the Codex seat decision and the engine."""
    identity = await resolve_seat_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return codex_seat_refused(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return codex_seat_refused(session)
    decision = await workspace_seat_decision(db, identity.workspace_id, codex=True, principal=await load_seat_principal(
        identity.user.id, session_id=session.id, client=str((session.metadata_ or {}).get("client") or "")))
    if not decision.allowed:
        return codex_seat_refused(refusal(STATE_DENIED, decision.reason, http_status=403))
    engine = await effective_engine(db, user_id=identity.user.id, workspace_id=identity.workspace_id)
    if ENGINE_CODEX not in engine.allowed:
        return codex_seat_refused(refusal(STATE_DENIED, REASON_ENGINE_NOT_ALLOWED, http_status=403, hint=_ENGINE_HINT))
    return identity, session, decision


@dataclass(frozen=True, slots=True)
class CodexSeatAdmission:
    """One admitted Codex seat call: the body (its model possibly mapped down by the run), the bytes of it the content
    decision read and the relay sends, and the Anthropic view the transcript records."""

    identity: GatewayIdentity
    session_id: str
    body: dict[str, Any]
    view: dict[str, Any]
    payload: bytes


async def admit_codex_seat(
    request: Request, db: AsyncSession, *, device: bool = False
) -> CodexSeatAdmission | Response:
    """Steps 1-4, shared by the relay route (``device=False``) and the device's admit (``codex_seat_device``).

    The platform switch ``seat_traffic`` must name the caller's way (never a silent fallback). On the device's way the
    server sends nothing upstream: its upstream configuration does not apply and the ChatGPT ``Authorization`` never
    reaches it (the launcher's seat proxy checks the login is there)."""
    context = await _codex_seat_context(request, db)
    if isinstance(context, Response):
        return context
    identity, session, decision = context
    outcome = gateway_outcome(request)
    outcome.bind(route=ROUTE_SEAT, workspace_id=identity.workspace_id, session_id=session.id,
                 user_id=identity.user.id)
    traffic = await seat_traffic(db)
    if traffic != (SEAT_TRAFFIC_DEVICE if device else SEAT_TRAFFIC_GATEWAY):
        return codex_seat_refused(refusal(STATE_NEEDS_CONFIGURATION, REASON_TRAFFIC_DEVICE if not device
                                          else REASON_TRAFFIC_GATEWAY, http_status=409, hint=_TRAFFIC_HINTS[traffic]))
    body = await _read_body(request, valid=is_responses_body, invalid_hint=BODY_INVALID_HINT)
    if isinstance(body, InboundRefusal):
        return codex_seat_refused(body)
    # The run's Codex model and budget, whatever the session asks; never a Claude model on this path.
    body = await run_limited_body(db, session.id, body, engine="codex")
    if isinstance(body, InboundRefusal):
        return codex_seat_refused(body)
    if decision.models and str(body.get("model") or "").strip() not in decision.models:
        # The Workspace's ``codex_seat_models``: another Codex model is refused, never swapped silently.
        return codex_seat_refused(refusal(STATE_DENIED, REASON_SEAT_MODEL_NOT_ALLOWED, http_status=403,
                                          hint="This Workspace allows these Codex models on your ChatGPT seat: "
                                               + ", ".join(decision.models) + "."))
    if not device:
        misconfigured = codex_seat_upstream_problem()
        if misconfigured:
            return codex_seat_refused(refusal(STATE_NEEDS_CONFIGURATION, misconfigured, http_status=503))
        if not str(request.headers.get("authorization") or "").strip():
            return codex_seat_refused(refusal(STATE_UNAUTHORIZED, REASON_SEAT_AUTHORIZATION_MISSING, http_status=401,
                                              hint=LOGIN_HINT))
    # The seat forwards the client's own body: the content decision reads that body, not the view.
    plan = await seat_content_plan(db, identity=identity, session=session, body=body, model=body["model"],
                                   headers=request.headers, outcome=outcome)
    if plan.refusal is not None:
        return codex_seat_refused(plan.refusal)
    view = anthropic_view(body)
    await touch_presence(db, identity.session_key, model=body["model"].strip())
    await db.commit()
    return CodexSeatAdmission(identity, session.id, body, view, plan.payload)


@recorded
async def handle_codex_seat_responses(request: Request, db: AsyncSession) -> Response:
    admitted = await admit_codex_seat(request, db)
    if isinstance(admitted, Response):
        return admitted
    identity, session_id, body, view = admitted.identity, admitted.session_id, admitted.body, admitted.view
    context = client_context(request.headers, CODEX_CONTEXT_HEADERS)
    client = build_codex_seat_client()
    started = time.perf_counter()
    outcome = gateway_outcome(request)
    upstream = await send_codex_seat(client, admitted.payload, request.headers, outcome)
    if isinstance(upstream, InboundRefusal):
        await client.aclose()
        return codex_seat_refused(upstream)
    await outcome.received(upstream.status_code)  # the headers arrived: sent, before any body is read
    notice = outcome.notice()
    headers = codex_seat_response_headers(upstream.headers)
    if notice:
        headers[HEADER_OBLIGATION] = notice
    # ChatGPT's rate-limit windows (``x-codex-primary/secondary-*``) into the presence allowance, like the Claude
    # seat: only the numbers, never a header value beyond them.
    await record_allowance(db, identity.session_key, parse_codex_allowance(upstream.headers), engine="codex")
    await db.commit()
    observation = Observation()

    def make_record() -> SeatCallRecord:
        return SeatCallRecord(
            session_id=session_id, user_id=identity.user.id, model=body["model"].strip(), body=view,
            observation=observation,
            upstream_request_id=headers.get("x-request-id", "") or headers.get("x-oai-request-id", ""),
            duration_ms=int((time.perf_counter() - started) * 1000), status_code=upstream.status_code,
            client_context=context, provider=CODEX_SEAT_PROVIDER, dispatch_owner=CODEX_SEAT_DISPATCH_OWNER,
        )

    if upstream.status_code >= 300 or body.get("stream") is not True:
        return await buffered_codex_answer(upstream, client, observation, headers, make_record)
    return streamed_codex_answer(upstream, client, observation, headers, make_record)


__all__ = [
    "CODEX_SEAT_DISPATCH_OWNER",
    "CODEX_SEAT_PROVIDER",
    "CodexSeatAdmission",
    "admit_codex_seat",
    "codex_seat_refused",
    "handle_codex_seat_responses",
]
