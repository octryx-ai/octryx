"""The custom content policies of the platform's own chat dispatch on the governed gateway route.

Called by the model-call boundary (``content_security.model_call``) for a driver that names a governed route (the
LiteLLM gateway driver's ``content_route``). Every chat request the platform sends through a gateway alias is
scanned (system messages and the newest turn) and asked as ``call_model`` with ``route=governed``, the alias'
approved categories and the request's principal (the admission carries it). The gateway's secret scan is not the
existing check on this path (the shipped platform policies mask credentials instead), so the generated
secret-scan policy is left out of the question and the shadow comparison stays equal.

Obligations follow the concept's precedence (``obligations``): shadow sends unchanged and states ``would_remedy`` (or
a would-be denial) in the call's one record (``ChatContent.evidence``, written by ``content_security.model_call``);
enforce masks the messages and/or switches to the policy's alias — chat is governed already, so a route only
changes the alias, which must be in the same gateway catalog, admitted for the Workspace and able to take the
request (tools, context) — then asks again. Anything else refuses as ``LiteLLMGatewayError(content_policy_denied,
<reason>)``. The call's one budget bounds every step up to the last scan: a masking pass that spends it refuses
the call unfinished (``content_scan_unfinished``, a notice without counts) before a target is chosen or asked. The
conversation is the chat session (sticky until a new chat).

A Workspace's content handling (``content_security.handling``) may reroute a kind found in the call: the model-call
boundary admits that alias with :func:`handling_target` (the same checks as an obligation's target) before the
custom policies are asked for it; a target that cannot take the call is ``content_route_unavailable``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ...runtime_limits import DEFAULT_APPROX_CHARS_PER_TOKEN
from ..content_detection.examination import RequestBudget
from ..content_detection.registry import detector_set_for
from ..model_gateway.litellm.alias_catalog import CAPABILITY_TOOLS
from ..model_gateway.litellm.errors import GATEWAY_STATE_CONTENT_POLICY_DENIED, LiteLLMGatewayError
from ..policy_engine.runtime import MODE_ENFORCE, current_runtime
from ..policy_engine.schema import ENTITY_AGENT_SESSION, ROUTE_GOVERNED
from ..policy_engine.shadow import LegacyDecision
from ..prompt_catalog import render_prompt
from .body_masking import mask_chat_messages
from .conversation_state import CHAT_CONVERSATION, load_state, remember
from .decision import (
    REASON_CONTENT_POLICY_DENIED,
    REASON_SCAN_UNFINISHED,
    ContentDecision,
    decide_model_content,
    scan_for,
)
from .obligations import (
    OUTCOME_REMEDIED,
    OUTCOME_WOULD_REMEDY,
    REASON_INSUFFICIENT,
    REASON_ROUTE_UNAVAILABLE,
    Obligation,
    Unresolved,
    resolve,
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
                          sensitive: frozenset[str] = frozenset(),
                          budget: RequestBudget | None = None) -> ContentDecision:
    """``budget``: the call's one budget (``content_security.model_call``): every scan here is charged to it."""
    scans = scan_for(chat_segments(list(messages)), admission.project_id, budget=budget)
    return decide_model_content(
        route=ROUTE_GOVERNED, alias=entry.alias, scans=scans, builtin_check=LegacyDecision(True),
        approved_for=entry.approved_data_categories, admission=admission, workspace_id=admission.project_id,
        principal=getattr(admission, "principal", None), sensitive=sensitive, builtin_secret_scan=False,
    )


def _refuse(reason: str, decision: ContentDecision | None = None, *, policies: Sequence[str] = (),
            model_from: str = "", model_to: str = "") -> LiteLLMGatewayError:
    """The refusal; with the first decision it carries the chat notice (names and counts only; the model-call
    boundary names its record). An unfinished examination's notice is the fixed one: no finding-derived count."""
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
    """The admitted entry of a content-handling reroute (``content_security.handling``: ``reroute`` /
    ``mask_reroute`` of a kind found in the call) — checked exactly like an obligation's route target (same
    catalog, admitted for the Workspace, tools, context) — or ``LiteLLMGatewayError(content_route_unavailable)``."""
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
    """The request to send (alias and messages), or raise ``LiteLLMGatewayError`` with the refusal reason. Every
    scan (both decisions, the obligation's masking pass) is charged to the call's ``budget``: once it is spent the
    request is unfinished (``content_scan_unfinished``)."""
    session_id = _session_id(admission)
    state = await load_state(session_id, CHAT_CONVERSATION)
    first = chat_content_decision(admission, entry, messages, state.categories, budget)
    if not first.scans.live.finished:  # unread text is refused in every mode, whatever Cedar answered
        raise _refuse(first.refusal, first, model_from=entry.alias)
    comparison = first.comparison
    denied = comparison is not None and comparison.cedar_allowed is False and not comparison.errors
    if not denied:
        if first.refusal:
            raise _refuse(first.refusal, first, model_from=entry.alias)
        return ChatContent(entry, messages, badge=partial(remember, session_id, CHAT_CONVERSATION, first.report))
    runtime = current_runtime()
    resolved = resolve(comparison.determining, runtime.custom_ids, runtime.custom_text)
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
    changed, masked, withheld = messages, 0, 0
    if obligation.masks:
        result = mask_chat_messages(messages, detector_set_for(runtime.custom_detectors, admission.project_id),
                                    obligation.mask, obligation.mask_style, budget)
        changed, masked, withheld = result.body, result.masked, result.withheld
    if budget is not None and budget.overrun:  # the masking pass spent the call's budget: nothing decided after it
        raise _refuse(REASON_SCAN_UNFINISHED, first, policies=obligation.policies, model_from=entry.alias)
    target = entry
    if obligation.reroutes and obligation.reroute_to != entry.alias:
        target = _target(admit, obligation.reroute_to, changed, tools, lambda: _refuse(
            REASON_ROUTE_UNAVAILABLE, first, policies=obligation.policies, model_from=entry.alias,
            model_to=obligation.reroute_to))
    second = chat_content_decision(admission, target, changed, sensitive | first.report.categories, budget)
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
