"""Budgets, dispatch and relay of an admitted inbound call whose content was decided (``service``, steps 4 and 6).

Also the path of a company model chosen in a seat session (``seat_company``) and of a seat request a content
policy routes to a governed alias, so those calls are governed exactly like one on the governed route.

The governed payload — the client's body with ``model`` replaced by the alias' model group (:func:`governed_payload`)
— is built before the content scan, and the bytes the scan's plan carries (``gateway_plan.InboundPlan.payload``) are
exactly what is sent. A budget refusal or an undelivered request is not a content refusal
(``GatewayOutcome.stopped``); a request whose response headers arrived was sent (``GatewayOutcome.received``),
and every answer returned carries the report notice.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.tool import BudgetLimitExceededError
from app.services.budget.enforcement import enforce_budget_limits

from ....runtime_limits import DEFAULT_APPROX_CHARS_PER_TOKEN
from ...agent_gateway.contract import STATE_DENIED, STATE_NEEDS_CONFIGURATION
from ...agent_gateway.daily_budget import check_daily_budget
from ...agent_gateway.identity import GatewayIdentity
from ...budget.unpriced_guard import REASON_UNPRICED_MODEL, UnpricedModelUnderCostCapError
from ...content_routing.gateway_outcome import STAGE_BUDGET, STAGE_UPSTREAM, GatewayOutcome
from ...content_routing.gateway_plan import HEADER_OBLIGATION
from ..litellm.errors import GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION
from .admission import InboundAdmission
from .anthropic_stream import Observation, SseRelay
from .call_context import client_context, render_refusal
from .refusals import (
    REASON_BUDGET_EXCEEDED,
    REASON_COUNT_TOKENS_UNSUPPORTED,
    InboundRefusal,
    refusal,
)
from .relay import relay_json, relay_stream
from .transcript import GatewayCallRecord
from .upstream import COUNT_TOKENS_PATH, MESSAGES_PATH, UpstreamAnswer, build_upstream_client, send_upstream

MAX_COUNT_TOKENS_RESPONSE_BYTES = 64 * 1024
# Upstream statuses that mean "this LiteLLM does not offer token counting".
_COUNT_TOKENS_UNSUPPORTED_STATUSES = frozenset({404, 405, 501})
REASON_COUNT_TOKENS_INVALID = "count_tokens_response_invalid"


def governed_payload(body: Mapping[str, Any], admitted: InboundAdmission) -> dict[str, Any]:
    """The payload a governed Messages or count-tokens call sends (and the content decision reads): the client's
    body with ``model`` replaced by the alias' model group."""
    return {**body, "model": admitted.entry.model_group}


def upstream_refusal(outcome: GatewayOutcome, upstream: InboundRefusal) -> InboundRefusal:
    """A failed upstream send: answered by the upstream (sent when its headers arrived), or not delivered
    (stopped)."""
    if isinstance(upstream, UpstreamAnswer):
        return outcome.named(upstream)
    return outcome.stopped(upstream, STAGE_UPSTREAM)


async def budget_refusal(
    db: AsyncSession, *, identity: GatewayIdentity, session_id: str, body: Mapping[str, Any],
    admitted: InboundAdmission,
) -> InboundRefusal | None:
    """Step 4 on an Anthropic-shaped body (``system``, ``messages``, ``max_tokens``); ``None``: within budget.

    Commits when it passes: the shadow session must be visible to the fresh session that records the call after
    the response (the request session may be closed by then).
    """
    daily = await check_daily_budget(db, user_id=identity.user.id, workspace_id=identity.workspace_id)
    if not daily.allowed:
        return refusal(daily.state, daily.reason, http_status=403, hint=daily.hint())
    try:
        await enforce_budget_limits(
            db,
            session_id=session_id,
            user_id=identity.user.id,
            project_id=identity.workspace_id,
            runtimes=[{"provider_name": admitted.provider_name, "model": admitted.entry.alias}],
            messages=[{"role": "system", "content": body.get("system") or ""}, *body["messages"]],
            max_completion_tokens=int(body.get("max_tokens") or 0),
            approx_chars_per_token=DEFAULT_APPROX_CHARS_PER_TOKEN,
        )
    except UnpricedModelUnderCostCapError as exc:
        return refusal(STATE_NEEDS_CONFIGURATION, REASON_UNPRICED_MODEL, hint=str(exc))
    except BudgetLimitExceededError:
        return refusal(STATE_DENIED, REASON_BUDGET_EXCEEDED)
    await db.commit()
    return None


async def dispatch_governed(
    db: AsyncSession,
    *,
    headers: Mapping[str, str],
    identity: GatewayIdentity,
    session_id: str,
    body: dict[str, Any],
    payload: bytes,
    admitted: InboundAdmission,
    outcome: GatewayOutcome,
) -> Response:
    """Steps 4 and 6 for an admitted call whose content was decided (``content_plan``): budgets, dispatch of
    ``payload`` (the plan's bytes of the scanned governed payload), relay and record; ``body``: the client's body
    (budget estimate, transcript).

    Also the path of a company model chosen in a seat session (``seat_company``), so that call is governed exactly
    like one on this route.
    ``outcome``: the request's one record (``gateway_outcome``); a reported kind's notice is returned as
    ``x-octryx-obligation``.
    """
    refused = await budget_refusal(db, identity=identity, session_id=session_id, body=body, admitted=admitted)
    if refused is not None:
        return render_refusal(outcome.stopped(refused, STAGE_BUDGET))

    context = client_context(headers)

    def make_record(observation: Observation, request_id: str, duration_ms: int, refused: str) -> GatewayCallRecord:
        return GatewayCallRecord(
            session_id=session_id,
            user_id=identity.user.id,
            provider_name=admitted.provider_name,
            entry=admitted.entry,
            body=body,
            observation=observation,
            upstream_request_id=request_id,
            duration_ms=duration_ms,
            evidence=admitted.evidence,
            client_context=context,
            refused_reason=refused,
        )

    client = build_upstream_client(admitted.config)
    started = time.perf_counter()
    upstream = await send_upstream(client, path=MESSAGES_PATH, body=payload, headers=headers,
                                   received=outcome.received)
    if isinstance(upstream, InboundRefusal):
        await client.aclose()
        return with_notice(render_refusal(upstream_refusal(outcome, upstream)), outcome)
    observation = Observation()
    if body.get("stream") is True:
        relay = SseRelay(entry=admitted.entry, observation=observation)
        response = await relay_stream(upstream, client, relay, started=started, make_record=make_record)
    else:
        response = await relay_json(
            upstream, client, observation, entry=admitted.entry, started=started, make_record=make_record
        )
    return with_notice(response, outcome)


async def count_tokens_governed(
    db: AsyncSession, *, headers: Mapping[str, str], payload: bytes, admitted: InboundAdmission,
    outcome: GatewayOutcome,
) -> Response:
    """Token counting of ``payload`` (the plan's bytes of the scanned governed payload); the report notice and the
    record's id travel on every answer."""
    await db.commit()
    client = build_upstream_client(admitted.config)
    try:
        upstream = await send_upstream(client, path=COUNT_TOKENS_PATH, body=payload, headers=headers,
                                       received=outcome.received)
        if isinstance(upstream, InboundRefusal):
            refused = upstream_refusal(outcome, upstream)
            if upstream.reason in {f"upstream_status_{code}" for code in _COUNT_TOKENS_UNSUPPORTED_STATUSES}:
                refused = outcome.named(refusal(STATE_NEEDS_CONFIGURATION, REASON_COUNT_TOKENS_UNSUPPORTED,
                                                http_status=404))
            return with_notice(render_refusal(refused), outcome)
        raw = b""
        async for chunk in upstream.aiter_bytes():
            raw += chunk
            if len(raw) > MAX_COUNT_TOKENS_RESPONSE_BYTES:
                raw = b""
                break
        await upstream.aclose()
    finally:
        await client.aclose()
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = None
    tokens = parsed.get("input_tokens") if isinstance(parsed, Mapping) else None
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
        return with_notice(render_refusal(
            InboundRefusal(GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION, REASON_COUNT_TOKENS_INVALID, 502)), outcome)
    return with_notice(JSONResponse({"input_tokens": tokens}), outcome)


def with_notice(response: Response, outcome: GatewayOutcome) -> Response:
    """``response`` with the request's report notice (``x-octryx-obligation``), if any."""
    notice = outcome.notice()
    if notice:
        response.headers[HEADER_OBLIGATION] = notice
    return response


__all__ = [
    "budget_refusal",
    "count_tokens_governed",
    "dispatch_governed",
    "governed_payload",
    "upstream_refusal",
    "with_notice",
]
