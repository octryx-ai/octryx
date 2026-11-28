"""The custom content policies of the platform's own chat dispatch on the governed gateway route."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ...runtime_limits import DEFAULT_APPROX_CHARS_PER_TOKEN
from ..content_detection.examination import RequestBudget
from ..content_detection.masking import PlaceholderSpans
from ..content_detection.registry import detector_set_for
from ..content_security.format_chat_messages import mask_chat_messages
from ..model_gateway.litellm.alias_catalog import CAPABILITY_TOOLS
from ..model_gateway.litellm.errors import GATEWAY_STATE_CONTENT_POLICY_DENIED, LiteLLMGatewayError
from ..policy_engine.runtime import MODE_ENFORCE, current_runtime
from ..policy_engine.schema import ENTITY_AGENT_SESSION, ROUTE_GOVERNED
from ..policy_engine.shadow import LegacyDecision
from ..prompt_catalog import render_prompt
from .conversation_state import CHAT_CONVERSATION, load_state, remember
from .decision import (
    REASON_CONTENT_POLICY_DENIED,
    REASON_SCAN_UNFINISHED,
    ContentDecision,
    decide_model_content,
    enforcement_budget,
    scan_for,
)
from .obligations import (
    OUTCOME_REMEDIED,
    OUTCOME_WOULD_REMEDY,
    REASON_INSUFFICIENT,
    REASON_ROUTE_UNAVAILABLE,
    Obligation,
    Unresolved,
    workspace_obligation,
)
from .segments import chat_segments

MASKED_NOTE_KEY = "secure_work.content.masked_note"


async def _nothing() -> None:
    return None


@dataclass(frozen=True, slots=True)
class ChatContent:
    entry: Any
    messages: list[dict[str, Any]]
    # What the turn shows the user (``content_obligation`` in the result), empty when nothing was changed.
    notice: Mapping[str, Any] = field(default_factory=dict)
    # The conversation's badge, counted by the caller only once the request was actually sent (I-4).
    badge: Callable[[], Awaitable[None]] = field(default=_nothing)
    # What the Workspace's policies did or would have done, for the call's one record (empty: nothing).
    evidence: Mapping[str, Any] = field(default_factory=dict)


def _session_id(admission: Any) -> str:
    principal = getattr(admission, "principal", None)
    ref = principal[0] if principal else None
    return ref.id if ref is not None and ref.type == ENTITY_AGENT_SESSION else ""


def chat_content_decision(admission: Any, entry: Any, messages: Sequence[Mapping[str, Any]],
                          sensitive: frozenset[str] = frozenset(), budget: RequestBudget | None = None,
                          placeholders: PlaceholderSpans | None = None) -> ContentDecision:
    scans = scan_for(chat_segments(list(messages)), admission.project_id, budget=budget, placeholders=placeholders)
    return decide_model_content(
        route=ROUTE_GOVERNED, alias=entry.alias, scans=scans, builtin_check=LegacyDecision(True),
        approved_for=entry.approved_data_categories, admission=admission, workspace_id=admission.project_id,
        principal=getattr(admission, "principal", None), sensitive=sensitive, builtin_secret_scan=False,
    )


def _refuse(reason: str, decision: ContentDecision | None = None, *, policies: Sequence[str] = (),
            model_from: str = "", model_to: str = "") -> LiteLLMGatewayError:
    found = {} if reason == REASON_SCAN_UNFINISHED or decision is None else decision.report.counts()
    notice = {"kind": "block", "reason": reason, "found": found, "masked": 0,
              "policies": list(policies or decision.policies), "decision_id": None,
              "model_from": model_from, "model_to": model_to} if decision is not None else None
    return LiteLLMGatewayError(GATEWAY_STATE_CONTENT_POLICY_DENIED, denial_reason=reason, content_notice=notice)


def _target(admit: Callable[[str], Any], alias: str, messages: list, tools: bool, refuse: Callable[[], Exception]
            ) -> Any:
    try:
        entry, _data = admit(alias)
    except LiteLLMGatewayError:
        raise refuse() from None
    if tools and CAPABILITY_TOOLS not in entry.requested_capabilities:
        raise refuse()
    if len(json.dumps(messages, ensure_ascii=False, default=str)) // DEFAULT_APPROX_CHARS_PER_TOKEN > \
            entry.context_limit:
        raise refuse()
    return entry


def handling_target(admit: Callable[[str], Any], alias: str, messages: list, *, tools: bool,
                    policies: Sequence[str], model_from: str) -> Any:
    def refuse() -> Exception:
        return LiteLLMGatewayError(GATEWAY_STATE_CONTENT_POLICY_DENIED, denial_reason=REASON_ROUTE_UNAVAILABLE,
                                   content_notice={"kind": "block", "reason": REASON_ROUTE_UNAVAILABLE, "found": {},
                                                   "masked": 0, "policies": list(policies), "decision_id": None,
                                                   "model_from": model_from, "model_to": alias})

    if not alias:
        raise refuse()
    return _target(admit, alias, messages, tools, refuse)


async def apply_chat_content(admission: Any, entry: Any, messages: list[dict[str, Any]], *,
                             admit: Callable[[str], Any], tools: bool,
                             budget: RequestBudget | None = None) -> ChatContent:
    session_id = _session_id(admission)
    state = await load_state(session_id, CHAT_CONVERSATION)
    first = chat_content_decision(admission, entry, messages, state.categories, budget)
    if not first.scans.live.finished:  # unread text is refused in every mode, whatever Cedar answered
        raise _refuse(first.refusal, first, model_from=entry.alias)
    comparison = first.comparison
    if not first.cedar_denied:
        if first.refusal:
            raise _refuse(first.refusal, first, model_from=entry.alias)
        return ChatContent(entry, messages, badge=partial(remember, session_id, CHAT_CONVERSATION, first.report))
    runtime = current_runtime()
    resolved = workspace_obligation(comparison.determining)
    enforce = runtime.mode == MODE_ENFORCE
    if isinstance(resolved, Unresolved) and enforce:
        raise _refuse(resolved.reason if resolved.reason != REASON_CONTENT_POLICY_DENIED else first.refusal
                      or REASON_CONTENT_POLICY_DENIED, first, policies=resolved.policies,
                      model_from=entry.alias)
    if isinstance(resolved, Unresolved) or not enforce:
        evidence: dict[str, Any] = {"outcome": "would_deny", "policies": list(resolved.policies), "decision": "deny"}
        if isinstance(resolved, Obligation):
            evidence = {"outcome": OUTCOME_WOULD_REMEDY, "policies": list(resolved.policies), "decision": "deny",
                        "obligation": _payload(resolved, entry.alias, applied=False, masked=0, second="")}
        return ChatContent(entry, messages, badge=partial(remember, session_id, CHAT_CONVERSATION, first.report),
                           evidence=evidence)
    return await _remedy(admission, entry, messages, first, resolved, state.categories, session_id, admit=admit,
                         tools=tools, budget=budget)


def _payload(obligation: Obligation, route_from: str, *, applied: bool, masked: int, second: str,
             withheld: int = 0) -> dict[str, Any]:
    to_alias = obligation.reroute_to if obligation.reroutes else ""
    return {"kind": obligation.kind, "applied": applied, "masked": masked, "withheld": withheld,
            "mask": sorted(obligation.mask),
            "mask_style": obligation.mask_style, "route_from": f"governed:{route_from}", "route_to": to_alias,
            "second_decision": second, "sticky": bool(to_alias)}


async def _remedy(admission: Any, entry: Any, messages: list[dict[str, Any]], first: ContentDecision,
                  obligation: Obligation, sensitive: frozenset[str], session_id: str, *,
                  admit: Callable[[str], Any], tools: bool, budget: RequestBudget | None) -> ChatContent:
    runtime = current_runtime()
    changed, masked, withheld, placeholders = messages, 0, 0, None
    if obligation.masks:
        result = mask_chat_messages(messages, detector_set_for(runtime.custom_detectors, admission.project_id),
                                    obligation.mask, obligation.mask_style, budget)
        changed, masked, withheld, placeholders = result.body, result.masked, result.withheld, result.placeholders
    if budget is not None and budget.overrun:  # the masking pass spent the call's budget: nothing decided after it
        raise _refuse(REASON_SCAN_UNFINISHED, first, policies=obligation.policies, model_from=entry.alias)
    target = entry
    if obligation.reroutes and obligation.reroute_to != entry.alias:
        target = _target(admit, obligation.reroute_to, changed, tools, lambda: _refuse(
            REASON_ROUTE_UNAVAILABLE, first, policies=obligation.policies, model_from=entry.alias,
            model_to=obligation.reroute_to))
    rescan = enforcement_budget() if budget is None and placeholders is not None else budget
    second = chat_content_decision(admission, target, changed, sensitive | first.report.categories, rescan,
                                   placeholders)
    if not second.allowed or second.comparison is None or second.comparison.cedar_allowed is not True:
        reason = REASON_SCAN_UNFINISHED if not second.scans.live.finished else REASON_INSUFFICIENT
        raise _refuse(reason, first, policies=obligation.policies, model_from=entry.alias)
    if masked:
        changed = [*changed, {"role": "system", "content": render_prompt(
            MASKED_NOTE_KEY, policies=", ".join(obligation.policies))}]
    evidence = {"outcome": OUTCOME_REMEDIED, "policies": list(obligation.policies), "decision": "deny",
                "obligation": _payload(obligation, entry.alias, applied=True, masked=masked, second="allow",
                                       withheld=withheld)}
    rerouted = target.alias != entry.alias
    badge = partial(remember, session_id, CHAT_CONVERSATION, first.report, policy_id=obligation.policies[0],
                    route_to=target.alias if rerouted else "")
    notice = {"kind": obligation.kind, "policies": list(obligation.policies), "decision_id": None,
              "found": first.report.counts(), "masked": masked, "model_from": entry.alias,
              "model_to": target.alias if rerouted else "", "reason": "content_obligation_applied"}
    return ChatContent(target, changed, notice, badge, evidence)


__all__ = ["ChatContent", "apply_chat_content", "chat_content_decision", "handling_target"]
