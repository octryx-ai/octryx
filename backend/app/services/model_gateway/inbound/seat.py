"""The seat route: a ``seat`` session's model calls to Anthropic with the user's own subscription.

``ANTHROPIC_BASE_URL=<platform>/api/v1/model-gateway/anthropic/seat``. One call runs, in this order,
and stops at the first explicit refusal (an Anthropic-shaped error with a fixed reason):

1. identity from the session-bound seat credential (``agent_gateway/seat_credential``): bound to the
   session key, user, Workspace and profile ``seat`` recorded at registration, re-checked on every call
   (expiry, finalize, grant revocation, user active, Workspace membership); then the existing session;
2. the Workspace's seat policy, re-checked on every call (``seat_mode``, ``requires_governed_routing``,
   classification at or above ``confidential``); there is no silent fallback to the governed route;
3. the request body (same bound and shape check as the governed route). A ``company/<alias>`` model is a
   company model the Workspace offers to seat sessions and leaves here for the governed path
   (``seat_company``); any other model must be in the allowlist (``seat_models``), then the gateway's content
   decision over the forwarded body runs (``content_routing.gateway_plan``: the fixed rules, the Workspace's content
   handling — ``secrets`` and ``credential_assignment``, ``refuse`` or ``report`` —, Cedar's ``call_model`` with
   ``route=seat`` and the resource ``ModelAlias::"seat:<model>"``): it refuses or the body goes on unchanged;
4. a subscription model's call goes to ``ANTHROPIC_SEAT_UPSTREAM`` with only the allowlisted request headers,
   including the client's own ``Authorization`` (``seat_upstream``). No platform budget is spent and no LiteLLM
   is used.

The upstream answer goes back **unchanged**: status, body, and the ``anthropic-ratelimit-*`` headers,
also for errors (a limit stop reads exactly as Anthropic wrote it). Its rate-limit headers update the
session's allowance (``agent_gateway/presence``); the observed usage and transcript are recorded after
the response (``seat_transcript``). The subscription token is never stored, logged or audited.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from typing import Any

import anyio
import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session
from ...agent_gateway.allowance import parse_allowance
from ...agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION, STATE_UNAUTHORIZED
from ...agent_gateway.identity import GatewayIdentity, GatewayRefusal
from ...agent_gateway.presence import record_allowance, touch_presence
from ...agent_gateway.seat_credential import EXPIRED_HINT, REASON_SEAT_SESSION_EXPIRED, resolve_seat_identity
from ...agent_gateway.seat_policy import SeatDecision, workspace_seat_decision
from ...agent_gateway.seat_policy_keys import REASON_SEAT_MODEL_NOT_ALLOWED
from ...agent_gateway.sessions import find_gateway_session
from ...content_routing.gateway_outcome import STAGE_UPSTREAM, GatewayOutcome, gateway_outcome, recorded
from ...content_routing.gateway_plan import HEADER_OBLIGATION
from ...policy_engine.request_principal import load_seat_principal
from ...policy_engine.schema import ROUTE_SEAT
from ..litellm.errors import GATEWAY_STATE_TIMEOUT, GATEWAY_STATE_UNREACHABLE
from .anthropic_stream import Observation
from .call_context import client_context
from .governed_dispatch import count_tokens_governed, dispatch_governed, governed_payload
from .model_listing import COMPANY_MODEL_PREFIX
from .refusals import (
    MODEL_NOT_ADMITTED_HINT,
    InboundRefusal,
    anthropic_error_response,
    refusal,
)
from .run_limits import run_limited_body
from .seat_company import SeatCompanyCall, admit_seat_company_call
from .seat_content import seat_content_plan
from .seat_observer import SeatSseObserver, observe_message
from .seat_transcript import SeatCallRecord, record_seat_call
from .seat_upstream import (
    build_seat_client,
    release_seat_client,
    seat_request_headers,
    seat_response_headers,
    seat_upstream_problem,
)
from .service import _read_body
from .upstream import COUNT_TOKENS_PATH, MESSAGES_PATH

MAX_SEAT_ERROR_BODY_BYTES = 64 * 1024
MAX_SEAT_JSON_BODY_BYTES = 16 * 1024 * 1024
REASON_SEAT_AUTHORIZATION_MISSING = "seat_subscription_login_missing"
REASON_UPSTREAM_TIMEOUT = "upstream_timeout"
REASON_UPSTREAM_UNREACHABLE = "upstream_unreachable"
REASON_REQUEST_HEADER_INVALID = "request_header_invalid"
LOGIN_HINT = "Sign in with your own Claude subscription in this octryx-claude profile: run /login."


def seat_refused(item: InboundRefusal | GatewayRefusal) -> Response:
    if isinstance(item, GatewayRefusal):
        hint = EXPIRED_HINT if item.reason == REASON_SEAT_SESSION_EXPIRED else ""
        item = refusal(item.state, item.reason, http_status=item.http_status, hint=hint)
    return anthropic_error_response(item)


async def seat_context(
    request: Request, db: AsyncSession
) -> tuple[GatewayIdentity, Session, SeatDecision] | Response:
    """Step 1 and 2: the seat identity, its session and the Workspace's seat decision for them."""
    identity = await resolve_seat_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return seat_refused(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return seat_refused(session)
    decision = await workspace_seat_decision(db, identity.workspace_id, principal=await load_seat_principal(
        identity.user.id, session_id=session.id, client=str((session.metadata_ or {}).get("client") or "")))
    if not decision.allowed:
        return seat_refused(refusal(STATE_DENIED, decision.reason, http_status=403))
    return identity, session, decision


async def _admitted_seat_request(
    request: Request, db: AsyncSession
) -> tuple[GatewayIdentity, str, dict[str, Any], bytes] | SeatCompanyCall | Response:
    """Steps 1-3; an admitted call carries the bytes of the payload its content decision read (a company call: the
    governed payload, ``governed_dispatch.governed_payload``; a subscription call: the client's body)."""
    context = await seat_context(request, db)
    if isinstance(context, Response):
        return context
    identity, session, decision = context
    outcome = gateway_outcome(request)
    outcome.bind(route=ROUTE_SEAT, workspace_id=identity.workspace_id, session_id=session.id,
                 user_id=identity.user.id)
    body = await _read_body(request)
    if isinstance(body, InboundRefusal):
        return seat_refused(body)
    body = await run_limited_body(db, session.id, body)  # the run's model and budget, whatever the session asks
    if isinstance(body, InboundRefusal):
        return seat_refused(body)
    model = body["model"].strip()
    if model.startswith(COMPANY_MODEL_PREFIX):
        # ``company/<alias>``: a governed call from this seat session, never the subscription.
        company = await admit_seat_company_call(
            db, identity=identity, session=session, decision=decision, body=body, headers=request.headers
        )
        if isinstance(company, InboundRefusal):
            return seat_refused(company)
        plan = await seat_content_plan(db, identity=identity, session=session,
                                       body=governed_payload(body, company.admitted), model=model,
                                       headers=request.headers, outcome=outcome, admitted=company.admitted)
        if plan.refusal is not None:
            return seat_refused(plan.refusal)
        return replace(company, payload=plan.payload)
    misconfigured = seat_upstream_problem()
    if misconfigured:
        return seat_refused(refusal(STATE_NEEDS_CONFIGURATION, misconfigured, http_status=503))
    if not str(request.headers.get("authorization") or "").strip():
        missing = refusal(STATE_UNAUTHORIZED, REASON_SEAT_AUTHORIZATION_MISSING, http_status=401, hint=LOGIN_HINT)
        return seat_refused(missing)
    if model not in decision.models:
        return seat_refused(refusal(STATE_DENIED, REASON_SEAT_MODEL_NOT_ALLOWED, http_status=400,
                                    hint=MODEL_NOT_ADMITTED_HINT))
    plan = await seat_content_plan(db, identity=identity, session=session, body=body, model=model,
                                   headers=request.headers, outcome=outcome)
    if plan.refusal is not None:
        return seat_refused(plan.refusal)
    await touch_presence(db, identity.session_key, model=model)
    await db.commit()
    return identity, session.id, body, plan.payload


async def _send(client: httpx.AsyncClient, path: str, content: bytes, headers: Mapping[str, str],
                outcome: GatewayOutcome):
    """``content``: the bytes the content decision read; a send that fails before the upstream answers is not a
    content refusal (``GatewayOutcome.stopped``)."""
    try:
        # A header value that cannot travel (non-ASCII) is the client's request error, never a 500.
        request = client.build_request(
            "POST", path, content=content,
            headers={**seat_request_headers(headers), "content-type": "application/json"},
        )
    except (UnicodeError, ValueError):
        return outcome.stopped(InboundRefusal(STATE_DENIED, REASON_REQUEST_HEADER_INVALID, 400), STAGE_UPSTREAM)
    try:
        upstream = await client.send(request, stream=True)
    except httpx.TimeoutException:
        return outcome.stopped(InboundRefusal(GATEWAY_STATE_TIMEOUT, REASON_UPSTREAM_TIMEOUT, 504), STAGE_UPSTREAM)
    except httpx.HTTPError:
        return outcome.stopped(InboundRefusal(GATEWAY_STATE_UNREACHABLE, REASON_UPSTREAM_UNREACHABLE, 502),
                               STAGE_UPSTREAM)
    return upstream


async def _bounded_bytes(response: httpx.Response, limit: int) -> bytes:
    raw = b""
    async for chunk in response.aiter_bytes():
        raw += chunk
        if len(raw) > limit:
            return raw[:limit]
    return raw


@recorded
async def handle_seat_messages(request: Request, db: AsyncSession) -> Response:
    admitted = await _admitted_seat_request(request, db)
    if isinstance(admitted, Response):
        return admitted
    outcome = gateway_outcome(request)
    if isinstance(admitted, SeatCompanyCall):
        return await dispatch_governed(db, headers=admitted.headers, identity=admitted.identity,
                                       session_id=admitted.session_id, body=admitted.body, payload=admitted.payload,
                                       admitted=admitted.admitted, outcome=outcome)
    identity, session_id, body, payload = admitted
    context = client_context(request.headers)
    client = build_seat_client()
    started = time.perf_counter()
    upstream = await _send(client, MESSAGES_PATH, payload, request.headers, outcome)
    if isinstance(upstream, InboundRefusal):
        await release_seat_client(client)
        return seat_refused(upstream)
    await outcome.received(upstream.status_code)  # the headers arrived: sent, before any body is read
    notice = outcome.notice()
    headers = seat_response_headers(upstream.headers)
    if notice:
        headers[HEADER_OBLIGATION] = notice
    await record_allowance(db, identity.session_key, parse_allowance(upstream.headers))
    await db.commit()
    observation = Observation()

    def make_record() -> SeatCallRecord:
        return SeatCallRecord(
            session_id=session_id, user_id=identity.user.id, model=body["model"].strip(), body=body,
            observation=observation, upstream_request_id=headers.get("request-id", ""),
            duration_ms=int((time.perf_counter() - started) * 1000), status_code=upstream.status_code,
            client_context=context,
        )
    if upstream.status_code >= 300 or body.get("stream") is not True:
        return await _buffered_answer(upstream, client, observation, headers, make_record)
    return _streamed_answer(upstream, client, observation, headers, make_record)


async def _buffered_answer(
    upstream: httpx.Response, client: httpx.AsyncClient, observation: Observation, headers: dict[str, str],
    make_record: Callable[[], SeatCallRecord],
) -> Response:
    limit = MAX_SEAT_ERROR_BODY_BYTES if upstream.status_code >= 300 else MAX_SEAT_JSON_BODY_BYTES
    try:
        raw = await _bounded_bytes(upstream, limit)
    except httpx.HTTPError:
        raw = b""
    finally:
        await upstream.aclose()
        await release_seat_client(client)
    if upstream.status_code < 300:
        try:
            observe_message(observation, json.loads(raw))
        except ValueError:
            pass
        await record_seat_call(make_record())
    return Response(content=raw, status_code=upstream.status_code, headers=headers)


def _streamed_answer(
    upstream: httpx.Response, client: httpx.AsyncClient, observation: Observation, headers: dict[str, str],
    make_record: Callable[[], SeatCallRecord],
) -> Response:
    observer = SeatSseObserver(observation)
    iterator = upstream.aiter_bytes()

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in iterator:
                observer.feed(chunk)
                yield chunk
            observer.finish()
        except (httpx.HTTPError, asyncio.CancelledError):
            # Mid-stream the status is already sent; the stream ends here and is recorded as incomplete.
            pass
        finally:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()
                await release_seat_client(client)
                await record_seat_call(make_record())

    return StreamingResponse(stream(), status_code=upstream.status_code, media_type="text/event-stream",
                             headers={**headers, "cache-control": "no-cache"})


@recorded
async def handle_seat_count_tokens(request: Request, db: AsyncSession) -> Response:
    """Token counting, passed through to Anthropic under the same checks; never an estimate."""
    admitted = await _admitted_seat_request(request, db)
    if isinstance(admitted, Response):
        return admitted
    outcome = gateway_outcome(request)
    if isinstance(admitted, SeatCompanyCall):
        return await count_tokens_governed(db, headers=admitted.headers, payload=admitted.payload,
                                           admitted=admitted.admitted, outcome=outcome)
    _identity, _session_id, _body, payload = admitted
    client = build_seat_client()
    upstream = await _send(client, COUNT_TOKENS_PATH, payload, request.headers, outcome)
    if isinstance(upstream, InboundRefusal):
        await release_seat_client(client)
        return seat_refused(upstream)
    await outcome.received(upstream.status_code)  # the headers arrived: sent, before any body is read
    notice = outcome.notice()
    try:
        raw = await _bounded_bytes(upstream, MAX_SEAT_ERROR_BODY_BYTES)
    except httpx.HTTPError:
        raw = b""
    finally:
        await upstream.aclose()
        await release_seat_client(client)
    headers = seat_response_headers(upstream.headers)
    if notice:
        headers[HEADER_OBLIGATION] = notice
    return Response(content=raw, status_code=upstream.status_code, headers=headers)


__all__ = [
    "handle_seat_count_tokens",
    "handle_seat_messages",
    "seat_context",
    "seat_refused",
]
