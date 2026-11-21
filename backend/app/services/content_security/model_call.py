"""The one content-security enforcement point of every model call, whatever the provider driver.

``agent.providers.base.BaseLLMProvider`` routes every driver's ``chat`` (LiteLLM gateway, Bedrock, OpenRouter,
Copilot, Ollama, Gemini, OpenAI-compatible) through :func:`enforced_chat`; a chat nested in another provider's
chat (a wrapper, a fallback) is the same request and is checked once, by the outer call. Chat turns, scheduled
tasks, governed runs and the platform's own helper calls (summaries, routing, extraction) all pass here.

System messages carry a trust level set by the prompt builder (``message_trust``): a platform instruction whose
text is exactly a shipped seed text (by content hash) is sent verbatim; any other platform instruction and authored
text (agent blueprint, reply format, Workspace workflow catalog, published catalog overrides) is masked, reported and
refused except for its role phrasing; every unmarked system message (memory, entity context, compaction,
checkpoint, repository knowledge, communication preferences, loop reminders) is checked like any other input. A
request whose messages are not a list of objects, whose structure nests deeper than ``request_examination.MAX_DEPTH``
or which carries text that is not valid Unicode is refused, typed (``content_unreadable``), before anything copies,
hashes or walks it.

What is done per sensitive content kind comes from the content-handling plan of the call's scope
(``model_call_scope``: the resolved Workspace, or an explicit platform scope with its reason; surface ``platform``:
the Workspace's setting per kind, else the shipped default — credentials and email masked, internal IPs reported);
the fixed rules (unfinished withheld, unreadable refused, prompt injection refused) come first and are not
configurable. A call without a scope is refused before anything is sent (``content_handling_scope_missing``,
:class:`~.model_call_scope.ModelCallScopeMissingError`), never decided on the shipped defaults; a plan that cannot be
read (``content_handling_unavailable``) or Workspaces of one call whose plans differ (``content_handling_conflict``)
refuse it too. Only a finished examination selects an action: an unfinished text or structure keeps its fixed
disposition (withheld) and its partial findings choose no refusal, reroute or record.

The call's one budget starts here (``examination.RequestBudget``: a deadline from entry to the final check, a cap on
each pass, every occurrence charged). The whole request is examined once (``request_examination``) with every
detector the plan acts on, by one walk of its provider copy (``model_call_masking``), and each finished field gets
its field-aware disposition (``model_call_fields``). Before the request is sent:

1. the refusals over the finished fields (``model_call_fields.refusing``): prompt injection (fixed) in every field
   (authored role phrasing exempt), then every kind the plan refuses in new message texts and extras and in the
   offered tool definitions; then unknown shapes and repeated argument keys (``content_unreadable``);
2. a kind the plan reroutes (``reroute`` / ``mask_reroute``) found anywhere switches the call to the Workspace's
   governance alias (:attr:`~.handling.HandlingPlan.governance_alias`), admitted like an obligation's target
   (``content_routing.chat.handling_target``); a direct driver cannot reroute → ``content_route_unavailable``, and
   neither can a Workspace without a governance alias or a target that is not admitted;
3. on the governed gateway route (a driver whose ``content_route`` names an admitted alias) the Workspace's published
   custom content policies (Cedar, ``content_routing.chat.apply_chat_content``) decide on the probe's copy — the
   request with every unfinished part withheld, never the original —: refuse, mask, or switch the alias;
4. the plan's masks (``mask``, ``mask_reroute``, and ``refuse`` for a refused kind left in older history or a
   replayed call) over the provider-bound copy; the reports wherever the content is sent, once per text. The caller's
   messages, tool calls and tools are not changed: local tool execution keeps the original arguments;
5. the route, after Cedar: a call a rerouting kind sent to the governance alias must still be going there (Cedar
   may choose another one) — else ``content_route_unavailable``;
6. the final check (``model_call_outbound``, ``content_detection.final_check``): the final request object the driver
   hands to its transport or SDK, read as one text, must carry neither prompt injection nor a kind the plan keeps
   out (``refuse``, ``mask``, ``mask_reroute``), a rerouting kind only when the call goes to the governance alias,
   and the call's budget must not be spent — else it is refused and nothing is sent. This is the guarantee; the masks
   above are what it verifies.

After the reply, before it is released: the same dispositions over the reply text and reasoning (``content``,
``thinking``); a refused kind or an unreadable answer refuses the reply, a rerouting kind is masked instead, a part
whose examination does not finish is withheld. The reply leaves no per-kind evidence. The reply's tool calls are
executed inside the platform as the model wrote them; they reach a provider only through the next request.

The call's one record (``model_call_outcome``, ``model_call_record``) is request-side and written when the call ends:
refused before anything was sent, or handed to the transport (from the final check's reading of the sent bytes;
a refused reply only adds ``reply_refused``); a call neither refused nor sent has none. The governed conversation's
badge is counted after that record.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Hashable, Mapping
from dataclasses import dataclass
from typing import Any

from ..content_detection.examination import DOMAIN_TEXT, RequestBudget, compose
from ..content_detection.final_check import REASON_FINAL_CHECK, REASON_ROUTE, REASON_UNFINISHED, FinalCheckRefused
from ..content_detection.request_examination import MAX_DEPTH, RequestExaminer, depth, utf8_clean
from ..content_detection.scanner import DetectorSet
from ..content_detection.vocabulary import DETECTOR_PROMPT_INJECTION
from ..model_gateway.litellm.errors import LiteLLMGatewayError
from .handling import (
    ACTION_REFUSE,
    MASKING,
    POINT_MODEL_CALL,
    POINT_MODEL_CALL_DIRECT,
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
from .model_call_masking import provider_messages, provider_tools, released_reply
from .model_call_outbound import bound_final, call_check
from .model_call_outcome import REASON_DENIED, REASON_UNREADABLE, CallOutcome
from .model_call_record import (
    STAGE_CEDAR,
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

_FINAL_POLICIES = {REASON_UNFINISHED: (POLICY_UNSCANNED_WITHHELD,)}


@dataclass(frozen=True, slots=True)
class GovernedContentRoute:
    """What a governed gateway driver gives the custom content policies: its admission, the admitted alias entry
    and how to admit another alias (a content policy may switch the alias)."""

    admission: Any
    entry: Any
    admit: Callable[[str], Any]


def _point(route: Any) -> str:
    return POINT_MODEL_CALL if route is not None else POINT_MODEL_CALL_DIRECT


def _evidence_scope() -> Hashable:
    """Whose reports ``model_call_fields.REPORTED`` keeps apart: the Workspace (or platform scope) and session."""
    scope = bound_scope()
    if scope is None:
        return ("", "")
    return (scope.workspace_id or (scope.platform.reason if scope.platform else ""), scope.session_id or "")


def _probe(messages: list[dict[str, Any]], tools: Any, examiner: RequestExaminer) -> tuple[RecordedRun, list[Any]]:
    """Every field the provider copy would carry, examined once (memoized for the copy itself), and the copy with
    every unfinished part withheld (its trust markers kept): what the governed Cedar decision reads."""
    run = RecordedRun(examiner, frozenset(), keep_trust=True)
    sanitized = provider_messages(messages, run)
    if isinstance(tools, list):
        provider_tools(tools, run)
    elif tools is not None:
        run.unreadable += 1
    return run, sanitized


def _refuse_request(probe: RecordedRun, model: str, plan: HandlingPlan, outcome: CallOutcome) -> None:
    """The refusals over the finished fields (``model_call_fields.refusing``), then unreadable content: nothing is
    sent. A field that was not fully examined is withheld from transport, and its partial findings refuse nothing."""
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


def _reroute(probe: RecordedRun, messages: list[dict[str, Any]], tools: Any, plan: HandlingPlan, route: Any,
             model: str, outcome: CallOutcome) -> Any:
    """The admitted entry of the Workspace's governance alias when a finished examination found a rerouting kind
    anywhere in the call, or ``None``; a withheld part chooses no target. A direct driver cannot reroute, nor can a
    Workspace without a governance alias or a target that is not admitted (``content_route_unavailable``, recorded
    with the target asked for)."""
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
    """The provider copy of the messages and tools, before dispatch: unreadable content refused, the rest masked
    or withheld (a refused kind left in older history is masked: it never leaves)."""
    run = RecordedRun(examiner, plan.kinds(*MASKING, ACTION_REFUSE))
    changed = provider_messages(messages, run)
    offered = provider_tools(tools, run) if isinstance(tools, list) else tools
    if run.unreadable:
        raise outcome.refuse((POLICY_UNREADABLE_REFUSED,), model, REASON_UNREADABLE, STAGE_INPUT)
    outcome.copied(run, reports(run, plan, _evidence_scope()))
    return changed, offered


def _mask_output(result: Any, outcome: CallOutcome, model: str, plan: HandlingPlan) -> Any:
    """The released reply (its own budget): an unreadable answer or reasoning refuses it, a refused kind refuses it,
    the rest masked or withheld — a rerouting kind is masked (the reply goes back to the user, not to another model).
    Only a finished examination selects an action; a part whose examination does not finish is withheld (the fixed
    disposition). The reply writes no per-kind evidence: a refusal only marks the call's record ``reply_refused``."""
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
    """The plan of the call's scope; no scope, an unreadable plan or conflicting Workspace plans refuse the call."""
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


def _readable_input(messages: Any, tools: Any) -> bool:
    """The supplied messages are a list (or none) of objects, nest no deeper than ``MAX_DEPTH`` and carry only valid
    Unicode text: checked before anything copies, hashes or walks them."""
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
        policies = _FINAL_POLICIES.get(refused_.reason, (POLICY_UNREADABLE_REFUSED,))
    return outcome.refuse(policies, model, refused_.reason, STAGE_FINAL_BYTES, entries=entries)


async def enforced_chat(provider: Any, chat: Callable[..., Awaitable[Any]], signature: inspect.Signature,
                        args: tuple, kwargs: dict[str, Any]) -> Any:
    """``chat(provider, *args, **kwargs)`` under the content handling (see the module doc); the call's one record is
    written when it ends, whatever ended it, and the governed conversation's badge is counted after it."""
    budget = RequestBudget()  # the call's entry: its one budget starts here
    bound = signature.bind(provider, *args, **kwargs)
    model = str(bound.arguments.get("model") or "")
    route = provider.content_route(model)
    outcome = CallOutcome(_point(route), model)
    try:
        result, badge = await _enforced(chat, bound, budget, route, model, outcome)
    except LiteLLMGatewayError as error:  # Cedar's refusal (or the governed driver's own failure)
        notice = error.content_notice
        if notice and outcome.refusal is None and outcome.sent is None:
            reason = str(error.denial_reason or "")
            policies = _FINAL_POLICIES.get(reason) or tuple(notice.get("policies") or ())
            outcome.refuse(policies, outcome.target or model, reason, STAGE_CEDAR)  # unfinished: the fixed outcome
        if notice and outcome.refusal is not None:
            notice["decision_id"] = outcome.decision_id
        raise
    finally:
        outcome.write()
    if badge is not None:  # the governed conversation's badge: only a sent request, after its record
        await badge()
    return result


async def _enforced(chat: Callable[..., Awaitable[Any]], bound: inspect.BoundArguments, budget: RequestBudget,
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
        raise outcome.refuse(_FINAL_POLICIES[REASON_UNFINISHED], model, REASON_UNFINISHED, STAGE_INPUT)
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


__all__ = ["GovernedContentRoute", "enforced_chat"]
