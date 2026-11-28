"""The gateway surface of content enforcement: one external coding agent's request refused, masked, rerouted or sent
unchanged, by the Workspace's content handling and its content policies (its rules: ``enforcement.GATEWAY``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_gateway.contract import STATE_DENIED
from ..content_detection.request_text import UnreadableRequestError
from ..content_routing.client_tool_results import client_tool_result_denial
from ..content_routing.conversation_state import load_state
from ..content_routing.decision import (
    REASON_CONTENT_POLICY_DENIED,
    REASON_CONTENT_POLICY_UNAVAILABLE,
    ContentDecision,
    content_detectors,
    decide_model_content,
)
from ..content_routing.gateway import (
    DENIED_HINT,
    content_refusal,
    fixed_refusal,
    handling_refusal,
    tool_result_refusal,
)
from ..content_routing.gateway_outcome import STAGE_BODY, STAGE_CONTENT, GatewayOutcome
from ..content_routing.obligations import Obligation, workspace_obligation
from ..model_gateway.inbound.refusals import REASON_BODY_INVALID, InboundRefusal, refusal
from ..policy_engine.runtime import MODE_ENFORCE, current_runtime
from ..policy_engine.schema import ROUTE_GOVERNED
from ..policy_engine.shadow import LegacyDecision
from .enforcement import GATEWAY
from .format_request_body import GatewayScan, examine_request_body, forwarded_bytes, mask_gateway_body
from .handling import (
    ACTION_REFUSE,
    MASKING,
    REASON_ROUTE_UNAVAILABLE,
    REROUTING,
    SURFACE_GATEWAY,
    HandlingPlan,
    content_handling,
)

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
    refusal: InboundRefusal | None = None
    found: tuple[dict[str, str], ...] = ()
    payload: bytes = b""
    body: Mapping[str, Any] | None = None  # the body as it is sent (masked where the plan masks)
    reroute: str = ""  # the alias the content requires; the route admits it and plans again


async def enforce_inbound(db: AsyncSession, request: InboundRequest) -> InboundPlan:
    outcome = request.outcome
    plan = await content_handling(db, request.workspace_id, SURFACE_GATEWAY)
    outcome.plan, outcome.route, outcome.alias = plan, request.route, request.alias
    outcome.conversation = request.conversation
    try:
        scan = examine_request_body(request.body, request.workspace_id, outcome.budget, plan.acting)
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
    refused = handling_refusal(plan, outcome, scan.newest.detected)
    if refused is not None:
        return InboundPlan(refusal=refused, found=scan.secret_kinds())
    rerouting = frozenset(outcome.requested) & plan.kinds(*REROUTING)
    if rerouting and request.alias != plan.governance_alias:
        return _rerouted(plan.governance_alias or "", plan.policies(rerouting, *REROUTING), outcome)
    denial = client_tool_result_denial(scan.tool_results, workspace_id=request.workspace_id,
                                       principal=request.principal) if GATEWAY.client_tool_check else None
    if denial is not None:
        return InboundPlan(refusal=tool_result_refusal(denial.tool, denial.reason, denial.policies,
                                                       denial.obligation, outcome), found=scan.secret_kinds())
    sensitive = (await load_state(outcome.session_id, request.conversation)).categories
    decision = _decided(request, scan, sensitive)  # Cedar reads the content as found, as on platform model calls
    obligation = _obligation(decision)
    if obligation is not None and obligation.reroutes and obligation.reroute_to != request.alias:
        outcome.cedar = {"policies": list(obligation.policies), "obligation": obligation.kind, "applied": "reroute"}
        return InboundPlan(reroute=obligation.reroute_to)
    remedy = obligation is not None and obligation.masks
    if decision.refusal and not remedy:
        return InboundPlan(refusal=content_refusal(decision, outcome), found=scan.secret_kinds())
    masking = frozenset(outcome.requested) & plan.kinds(*MASKING, ACTION_REFUSE)  # refuse: older turns only here
    masking |= obligation.mask if remedy else frozenset()
    body, sent = _masked(request, masking, plan.acting, outcome) if masking else (request.body, scan)
    if body is None:
        return InboundPlan(refusal=_unmasked(plan, masking, outcome), found=scan.secret_kinds())
    if remedy:  # the policy's mask applied: it decides again on what is sent
        decision = _decided(request, sent, sensitive | decision.report.categories)
        if decision.refusal:
            return InboundPlan(refusal=content_refusal(decision, outcome), found=scan.secret_kinds())
        outcome.cedar = {"policies": list(obligation.policies), "obligation": obligation.kind, "applied": "mask"}
    comparison = decision.comparison
    if comparison is not None and comparison.cedar_allowed is False:  # shadow: what Cedar would have done
        outcome.cedar = {"policies": list(comparison.determining), "would": "deny", "applied": "none"}
    try:
        payload = forwarded_bytes(body)
    except UnreadableRequestError:
        return InboundPlan(refusal=outcome.refuse(refusal(STATE_DENIED, REASON_BODY_INVALID, http_status=400),
                                                  STAGE_BODY, fixed="unreadable"))
    if outcome.budget.overrun:  # the bytes to send are content work too: past the deadline only the fixed outcome
        outcome.requested, outcome.newest = {}, None
        return InboundPlan(refusal=fixed_refusal(scan, outcome, False))
    return InboundPlan(payload=payload, body=body)


def _rerouted(alias: str, policies: tuple[str, ...], outcome: GatewayOutcome) -> InboundPlan:
    if alias:
        return InboundPlan(reroute=alias)
    return InboundPlan(refusal=outcome.refuse(refusal(
        STATE_DENIED, REASON_ROUTE_UNAVAILABLE, http_status=403,
        hint=f"Content handling {', '.join(policies)} sends this request to the Workspace's governance model, and "
             f"none is set. {DENIED_HINT}"), STAGE_CONTENT, policies=policies))


# Masks the kinds in the body, then reads it again: what is sent is checked, not what was meant to be sent.
def _masked(request: InboundRequest, kinds: frozenset[str], acting: frozenset[str],
            outcome: GatewayOutcome) -> tuple[Mapping[str, Any] | None, GatewayScan]:
    detectors, _published = content_detectors(request.workspace_id)
    masked = mask_gateway_body(request.body, detectors, kinds, outcome.budget)
    again = examine_request_body(masked.body, request.workspace_id, outcome.budget, acting | kinds)
    outcome.content = {**outcome.content, "masked": masked.masked, "withheld": masked.withheld}
    outcome.masked = outcome.masked | kinds
    if not again.finished or outcome.budget.overrun or again.body.live.detected & kinds:
        return None, again
    return masked.body, again


def _unmasked(plan: HandlingPlan, kinds: frozenset[str], outcome: GatewayOutcome) -> InboundRefusal:
    return outcome.refuse(refusal(STATE_DENIED, REASON_CONTENT_POLICY_DENIED, http_status=403,
                                  hint=f"This request could not be masked completely, so it was not sent. "
                                       f"{DENIED_HINT}"),
                          STAGE_CONTENT, policies=plan.policies(kinds, *MASKING, ACTION_REFUSE), fixed="final_bytes")


# The Workspace's content handling is the one secret rule here (no second built-in decision), as on platform calls.
def _decided(request: InboundRequest, scan: GatewayScan, sensitive: frozenset[str]) -> ContentDecision:
    return decide_model_content(
        route=request.route, alias=request.alias, scans=scan.body, builtin_check=LegacyDecision(True),
        approved_for=request.approved_for, admission=request.admission if request.route == ROUTE_GOVERNED else None,
        workspace_id=request.workspace_id, classification=request.classification, principal=request.principal,
        sensitive=sensitive, builtin_secret_scan=False)


# A custom policy's mask or reroute, applied instead of refusing (enforce mode only; a plain block still refuses).
def _obligation(decision: ContentDecision) -> Obligation | None:
    if not decision.refusal or decision.refusal == REASON_CONTENT_POLICY_UNAVAILABLE or not decision.policies:
        return None
    if current_runtime().mode != MODE_ENFORCE:
        return None
    resolved = workspace_obligation(decision.policies)
    return resolved if isinstance(resolved, Obligation) else None


__all__ = ["HEADER_OBLIGATION", "InboundPlan", "InboundRequest", "enforce_inbound"]
