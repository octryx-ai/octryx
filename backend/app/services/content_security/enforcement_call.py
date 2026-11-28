"""The platform surface of content enforcement: one provider call, from its examination to the reply it releases."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Hashable, Mapping
from typing import Any

from ..content_detection.examination import DOMAIN_TEXT, RequestBudget, compose
from ..content_detection.final_check import REASON_FINAL_CHECK, REASON_ROUTE, REASON_UNFINISHED, FinalCheckRefused
from ..content_detection.request_examination import MAX_DEPTH, RequestExaminer, depth, utf8_clean
from ..content_detection.scanner import DetectorSet
from ..content_detection.vocabulary import DETECTOR_PROMPT_INJECTION
from ..model_gateway.litellm.errors import LiteLLMGatewayError
from .format_chat_messages import provider_messages, provider_tools
from .handling import (
    ACTION_REFUSE,
    MASKING,
    POLICY_PROMPT_INJECTION_REFUSED,
    POLICY_UNREADABLE_REFUSED,
    POLICY_UNSCANNED_WITHHELD,
    REASON_HANDLING_SCOPE_MISSING,
    REASON_HANDLING_UNAVAILABLE,
    REASON_ROUTE_UNAVAILABLE,
    REROUTING,
    SURFACE_PLATFORM,
    ContentHandlingUnavailableError,
    HandlingPlan,
)
from .model_call_fields import RecordedRun, refusing, reports
from .model_call_masking import released_reply
from .model_call_outbound import bound_final, call_check
from .model_call_outcome import REASON_DENIED, REASON_UNREADABLE, CallOutcome
from .model_call_record import (
    STAGE_FINAL_BYTES,
    STAGE_INPUT,
    STAGE_REROUTE,
    SURFACE_OFFERED_TOOLS,
    SURFACE_REQUEST,
    Applied,
    refused,
    route_unavailable,
)
from .model_call_scope import (
    REASON_HANDLING_CONFLICT,
    ContentHandlingConflictError,
    ModelCallScopeMissingError,
    bound_scope,
    scope_plan,
)
from .transport import TransportRun

FINAL_POLICIES = {REASON_UNFINISHED: (POLICY_UNSCANNED_WITHHELD,)}


def _evidence_scope() -> Hashable:
    scope = bound_scope()
    if scope is None:
        return ("", "")
    return (scope.workspace_id or (scope.platform.reason if scope.platform else ""), scope.session_id or "")


def _probe(messages: list[dict[str, Any]], tools: Any, examiner: RequestExaminer) -> tuple[RecordedRun, list[Any]]:
    run = RecordedRun(examiner, frozenset(), keep_trust=True)
    sanitized = provider_messages(messages, run)
    if isinstance(tools, list):
        provider_tools(tools, run)
    elif tools is not None:
        run.unreadable += 1
    return run, sanitized


def _refuse_request(probe: RecordedRun, model: str, plan: HandlingPlan, outcome: CallOutcome) -> None:
    injection, found, per_surface = refusing(probe, plan)
    if DETECTOR_PROMPT_INJECTION in injection.detected:
        raise outcome.refuse((POLICY_PROMPT_INJECTION_REFUSED,), model, REASON_DENIED, STAGE_INPUT,
                             examination=injection)
    policies = plan.policies(found.detected, ACTION_REFUSE)
    if policies:
        entries = [entry for surface, kinds in per_surface.items() for entry in refused(plan, surface, kinds)]
        raise outcome.refuse(policies, model, REASON_DENIED, STAGE_INPUT, examination=found, entries=entries)
    if probe.unreadable:
        raise outcome.refuse((POLICY_UNREADABLE_REFUSED,), model, REASON_UNREADABLE, STAGE_INPUT)


# Only a finished examination chooses a target; a direct driver, a Workspace without a governance alias or an alias that
# is not admitted cannot reroute (content_route_unavailable, recorded with the target asked for).
def _reroute(probe: RecordedRun, messages: list[dict[str, Any]], tools: Any, plan: HandlingPlan, route: Any,
             model: str, outcome: CallOutcome) -> Any:
    found = probe.detected()
    kinds = frozenset().union(*found.values()) & plan.kinds(*REROUTING)
    if not kinds:
        return None
    policies = plan.policies(kinds, *REROUTING)
    target = {"requested": model, "handling": plan.governance_alias or "", "final": "", "admitted": False}
    entries = route_unavailable(plan, found)
    if route is None or not target["handling"]:
        raise outcome.refuse(policies, model, REASON_ROUTE_UNAVAILABLE, STAGE_REROUTE, entries=entries, target=target)
    from ..content_routing.chat import handling_target

    try:
        return handling_target(route.admit, target["handling"], messages, tools=bool(tools), policies=policies,
                               model_from=model)
    except LiteLLMGatewayError as error:
        outcome.refuse(policies, model, REASON_ROUTE_UNAVAILABLE, STAGE_REROUTE, entries=entries, target=target)
        error.content_notice["decision_id"] = outcome.decision_id
        raise


def _mask_input(messages: list[dict[str, Any]], tools: Any, examiner: RequestExaminer, outcome: CallOutcome,
                model: str, plan: HandlingPlan) -> tuple[list[dict], Any]:
    run = RecordedRun(examiner, plan.kinds(*MASKING, ACTION_REFUSE))
    changed = provider_messages(messages, run)
    offered = provider_tools(tools, run) if isinstance(tools, list) else tools
    if run.unreadable:
        raise outcome.refuse((POLICY_UNREADABLE_REFUSED,), model, REASON_UNREADABLE, STAGE_INPUT)
    outcome.copied(run, reports(run, plan, _evidence_scope()))
    return changed, offered


# The reply goes back to the person, not to another model: a rerouting kind is masked, and the reply writes no per-kind
# evidence (a refusal only marks the call's record ``reply_refused``).
def _mask_output(result: Any, outcome: CallOutcome, model: str, plan: HandlingPlan) -> Any:
    if not isinstance(result, dict):
        return result
    examiner = RequestExaminer(DetectorSet(builtin=plan.acting), RequestBudget())
    run = TransportRun(examiner, plan.kinds(*MASKING, *REROUTING))
    released = released_reply(result, run)
    if run.unreadable:
        raise outcome.reply_refusal((POLICY_UNREADABLE_REFUSED,), model, REASON_UNREADABLE)
    refusing_kinds = plan.kinds(ACTION_REFUSE)
    examination = compose([item for item in run.examinations if item.finished],
                          domain=DOMAIN_TEXT).restricted(refusing_kinds)
    if examination.detected:
        raise outcome.reply_refusal(plan.policies(examination.detected, ACTION_REFUSE), model, REASON_DENIED,
                                    examination)
    return released


async def _plan(model: str, outcome: CallOutcome) -> HandlingPlan:
    scope = bound_scope()
    if scope is None:
        outcome.refuse((), model, REASON_HANDLING_SCOPE_MISSING, STAGE_INPUT)
        raise ModelCallScopeMissingError("a driver call without a model call scope", model, outcome.decision_id)
    try:
        return await scope_plan(scope, SURFACE_PLATFORM)
    except ContentHandlingUnavailableError:
        raise outcome.refuse((), model, REASON_HANDLING_UNAVAILABLE, STAGE_INPUT) from None
    except ContentHandlingConflictError:
        raise outcome.refuse((), model, REASON_HANDLING_CONFLICT, STAGE_INPUT) from None


# Checked before anything copies, hashes or walks the request.
def _readable_input(messages: Any, tools: Any) -> bool:
    if messages is not None and not (isinstance(messages, list) and all(isinstance(item, dict) for item in messages)):
        return False
    request = {"messages": messages or [], "tools": tools}
    return depth(request) <= MAX_DEPTH and utf8_clean(request)


def _final_refusal(outcome: CallOutcome, plan: HandlingPlan, model: str, refused_: FinalCheckRefused) -> Exception:
    entries: list[Applied] = []
    if refused_.reason == REASON_FINAL_CHECK:
        policies = plan.policies(refused_.kinds, ACTION_REFUSE, *MASKING)
        entries = [Applied(SURFACE_REQUEST, kind, plan.action(kind), ACTION_REFUSE, REASON_FINAL_CHECK)
                   for kind in sorted(refused_.kinds - {DETECTOR_PROMPT_INJECTION}) if kind in plan.acting]
        if DETECTOR_PROMPT_INJECTION in refused_.kinds:
            policies = (POLICY_PROMPT_INJECTION_REFUSED, *policies)
    elif refused_.reason == REASON_ROUTE:
        policies = plan.policies(refused_.kinds, *REROUTING)
        entries = [Applied(SURFACE_REQUEST, kind, plan.action(kind), ACTION_REFUSE, REASON_ROUTE)
                   for kind in sorted(refused_.kinds) if kind in plan.acting]
    else:
        policies = FINAL_POLICIES.get(refused_.reason, (POLICY_UNREADABLE_REFUSED,))
    return outcome.refuse(policies, model, refused_.reason, STAGE_FINAL_BYTES, entries=entries)


async def enforce_call(chat: Callable[..., Awaitable[Any]], bound: inspect.BoundArguments, budget: RequestBudget,
                    route: Any, model: str, outcome: CallOutcome) -> tuple[Any, Callable[[], Awaitable[None]] | None]:
    supplied = bound.arguments.get("messages")
    tools = bound.arguments.get("tools")
    plan = outcome.plan = await _plan(model, outcome)
    if not _readable_input(supplied, tools):
        raise outcome.refuse((POLICY_UNREADABLE_REFUSED,), model, REASON_UNREADABLE, STAGE_INPUT)
    messages = list(supplied or [])
    examiner = RequestExaminer(DetectorSet(builtin=frozenset({DETECTOR_PROMPT_INJECTION}) | plan.acting), budget)
    probe, sanitized = _probe(messages, tools, examiner)
    outcome.input = probe
    if budget.overrun:  # the deadline passed during the examination: the fixed outcome, no finding decides
        raise outcome.refuse(FINAL_POLICIES[REASON_UNFINISHED], model, REASON_UNFINISHED, STAGE_INPUT)
    _refuse_request(probe, model, plan, outcome)
    rerouted = _reroute(probe, messages, tools, plan, route, model, outcome)
    required = outcome.rerouted = rerouted.alias if rerouted is not None else ""
    cedar_notice: Mapping[str, Any] = {}
    badge = None
    if route is not None:
        from ..content_routing.chat import apply_chat_content

        content = await apply_chat_content(route.admission, rerouted or route.entry, sanitized, admit=route.admit,
                                           tools=bool(tools), budget=budget)
        messages, model, cedar_notice, badge = content.messages, content.entry.alias, content.notice, content.badge
        outcome.cedar, outcome.target = content.evidence, model
        # Cedar and the copy start from the messages the probe withheld in (the tools are walked again below).
        outcome.withhold({surface: count for surface, count in probe.withheld_at.items()
                          if surface != SURFACE_OFFERED_TOOLS})
    if required and model != required:  # the route the content requires, checked after Cedar, right before send
        raise outcome.refuse(plan.policies(plan.kinds(*REROUTING), *REROUTING), model, REASON_ROUTE_UNAVAILABLE,
                             STAGE_REROUTE, target={"requested": outcome.requested, "handling": required,
                                                    "final": model, "admitted": False})
    sent, offered = _mask_input(messages, tools, examiner, outcome, model, plan)
    bound.arguments["messages"] = sent
    if "tools" in bound.arguments:
        bound.arguments["tools"] = offered
    if "model" in bound.arguments:
        bound.arguments["model"] = model
    outcome.model = model
    try:
        with bound_final(call_check(plan, budget, messages, sent, model, outcome.dispatched)):
            reply = await chat(*bound.args, **bound.kwargs)
    except FinalCheckRefused as refused_:
        raise _final_refusal(outcome, plan, model, refused_) from None
    released = _mask_output(reply, outcome, model, plan)
    return outcome.forwarded(released, model, cedar_notice), badge


__all__ = ["FINAL_POLICIES", "enforce_call"]
