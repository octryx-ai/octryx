"""The content decision of one external coding agent's request at the inbound gateway: refuse, or send unchanged.

:func:`plan_inbound` runs for every gateway route (the Anthropic route and the Claude Code seat — Messages bodies —,
the ``/openai`` route and the Codex seat — Responses bodies) on the body each forwards, in this order, and stops at
the first refusal (each typed, and recorded once by the request's ``gateway_outcome``):

1. the passes over the body (``gateway.scan_request``; a body that cannot be read as JSON text is the typed body
   refusal ``request_body_invalid``) and the bytes to send, then one reading of the request's clock, and the fixed
   rules: an unfinished pass or a deadline passed during that content work (no finding recorded), then prompt
   injection in a tool result (``gateway.fixed_refusal``; the completed examination's kinds and the injection's
   count and source are recorded with it) — before any policy query, so neither Cedar nor a record sees partial
   findings;
2. the Workspace's content handling, surface ``gateway`` (``secrets`` and ``credential_assignment`` only): a kind
   found that is set to ``refuse`` refuses (``gateway.handling_refusal``); ``report`` lets it on and is recorded;
3. a Workspace policy on a client tool's results (``client_tool_results``) refuses;
4. the Workspace's Cedar question over the whole body's findings (``decision.decide_model_content``, with the
   conversation's categories): enforce denying, or unable to answer, refuses — a deciding policy's mask or reroute
   obligation is never applied here (``content_handling_gateway_refused``); in shadow mode a would-be denial is
   stated in the request's record.

Otherwise the request goes on unchanged: the plan carries the bytes of the scanned payload (:attr:`InboundPlan.payload`)
and the route sends exactly those and marks it sent (``GatewayOutcome.sent``). A refusal carries the bounded, redacted
credential kinds found (:attr:`InboundPlan.found`), which the run's timeline note uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_gateway.contract import STATE_DENIED
from ..content_detection.request_text import UnreadableRequestError
from ..content_detection.vocabulary import DETECTOR_SECRETS
from ..content_security.handling import ACTION_REFUSE, SURFACE_GATEWAY, content_handling
from ..model_gateway.inbound.refusals import REASON_BODY_INVALID, REASON_SECRET_DETECTED, InboundRefusal, refusal
from ..policy_engine.schema import ROUTE_GOVERNED
from ..policy_engine.shadow import LegacyDecision
from .client_tool_results import client_tool_result_denial
from .conversation_state import load_state
from .decision import builtin_secret_decision, decide_model_content
from .gateway import (
    content_refusal,
    fixed_refusal,
    forwarded_bytes,
    handling_refusal,
    scan_request,
    tool_result_refusal,
)
from .gateway_outcome import STAGE_BODY, GatewayOutcome

HEADER_OBLIGATION = "x-octryx-obligation"


@dataclass(frozen=True, slots=True)
class InboundRequest:
    body: Mapping[str, Any]  # the final payload, exactly as it is sent
    outcome: GatewayOutcome  # the request's record (``gateway_outcome.recorded``)
    route: str
    workspace_id: str
    conversation: str
    alias: str
    approved_for: frozenset[str] = frozenset()
    admission: Any = None  # the governed route's ProjectModelAdmission
    principal: Any = None
    classification: Any = None


@dataclass(frozen=True, slots=True)
class InboundPlan:
    """``refusal`` when the request is not sent (``found``: the credential kinds found); else ``payload``: the bytes
    of the scanned payload, which the route sends."""

    refusal: InboundRefusal | None = None
    found: tuple[dict[str, str], ...] = ()
    payload: bytes = b""


async def plan_inbound(db: AsyncSession, request: InboundRequest) -> InboundPlan:
    outcome = request.outcome
    plan = await content_handling(db, request.workspace_id, SURFACE_GATEWAY)
    outcome.plan, outcome.route, outcome.alias = plan, request.route, request.alias
    outcome.conversation = request.conversation
    try:
        scan = scan_request(request.body, request.workspace_id, outcome.budget)
        payload = forwarded_bytes(request.body)
    except UnreadableRequestError:
        return InboundPlan(refusal=outcome.refuse(refusal(STATE_DENIED, REASON_BODY_INVALID, http_status=400),
                                                  STAGE_BODY, fixed="unreadable"))
    # The one clock reading after all content work (the passes, the structured fields, the bytes to send).
    finished = scan.finished and not outcome.budget.overrun
    if finished:  # completion first: nothing partial reaches Cedar or a record
        outcome.content = scan.body.live.report.summary()
        outcome.newest = scan.newest.report
        outcome.requested = {kind: plan.action(kind) for kind in sorted(scan.body.live.detected & plan.acting)}
    fixed = fixed_refusal(scan, outcome, finished)
    if fixed is not None:
        return InboundPlan(refusal=fixed, found=scan.secret_kinds() if finished else ())
    refused = handling_refusal(plan, outcome)
    if refused is not None:
        return InboundPlan(refusal=refused, found=scan.secret_kinds())
    denial = client_tool_result_denial(scan.tool_results, workspace_id=request.workspace_id,
                                       principal=request.principal)
    if denial is not None:
        return InboundPlan(refusal=tool_result_refusal(denial.tool, denial.reason, denial.policies,
                                                       denial.obligation, outcome), found=scan.secret_kinds())
    state = await load_state(outcome.session_id, request.conversation)
    secrets_refused = plan.action(DETECTOR_SECRETS) == ACTION_REFUSE
    builtin = builtin_secret_decision(scan.body, REASON_SECRET_DETECTED) if secrets_refused else (
        LegacyDecision(True))
    decision = decide_model_content(
        route=request.route, alias=request.alias, scans=scan.body, builtin_check=builtin,
        approved_for=request.approved_for, admission=request.admission if request.route == ROUTE_GOVERNED else None,
        workspace_id=request.workspace_id, classification=request.classification, principal=request.principal,
        sensitive=state.categories, builtin_secret_scan=secrets_refused)
    if decision.refusal:
        return InboundPlan(refusal=content_refusal(decision, outcome), found=scan.secret_kinds())
    comparison = decision.comparison
    if comparison is not None and comparison.cedar_allowed is False:  # shadow: what Cedar would have done
        outcome.cedar = {"policies": list(comparison.determining), "would": "deny", "applied": "none"}
    return InboundPlan(payload=payload)


__all__ = ["HEADER_OBLIGATION", "InboundPlan", "InboundRequest", "plan_inbound"]
