"""The content check of an external coding agent's request at the inbound gateway (all four routes).

The gateway forwards the final payload it scanned or refuses it: a governed route builds that payload (the alias'
model group, the effective output cap) before the scan, a seat sends the client's body as it is, and the bytes sent
are serialized from the scanned object (``gateway_plan.InboundPlan.payload``), so there is no separate final check
here. What it reads (README "Sensitive content handling" states
the threat model: accidental leakage by the user's own coding agent, and prompt injection arriving in tool results):

The built-in detectors of the gateway are ``secrets`` and ``credential_assignment`` only (``handling.GATEWAY_KINDS``),
plus prompt injection in the tool-result pass; the Workspace's custom detectors run in every pass. The platform-only
built-in kinds (email, internal IP, IBAN, phone) are never examined here, so they reach no gateway policy question,
record or badge.

- **the whole body** as one text (``content_detection.request_text``: its JSON serialization but the exact opaque
  key list) with the gateway's detectors, plus the structured credential assignments of its parsed
  keys and values (``request_text.credential_values``: a field whose name ends in a credential name assigning a
  literal value — in tool arguments, tool results and prompt data, serialized JSON strings included —, the opaque
  list honored; one ``credential_assignment`` finding each, unless the text detector already found that value) —
  the Workspace's content handling acts on ``secrets`` and ``credential_assignment`` only (``refuse`` or
  ``report``, the same classification for both; defaults: credentials refused, assignments reported); these
  findings go to the Workspace's Cedar question;
- **each tool result** as one text (with its structured credential assignments) — Anthropic ``tool_result``
  blocks of ``messages[].content``, Responses ``function_call_output`` and ``*_call_output`` items of ``input`` —
  with the gateway's detectors and prompt injection: prompt injection there refuses the request; the findings per
  tool go to the Workspace's tool-result policies (``client_tool_results``);
- **the newest turn** (what follows the last assistant message or item) for the conversation's badge only.

Nothing is validated beyond JSON parsing (``model_gateway.inbound.service``): no protocol shape, no tool name or type;
a body that cannot be serialized as JSON text (``request_text.UnreadableRequestError``) is the typed body refusal
(``request_body_invalid``). Each pass is charged to the request's one budget (``examination.RequestBudget``, started
at handler entry); a pass that does not finish refuses the request (``content_scan_unfinished``). The refusals are
typed and recorded once (``gateway_outcome``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ..agent_gateway.contract import STATE_DENIED
from ..content_detection.examination import DOMAIN_TEXT, Examination, RequestBudget, compose, examine, examine_each
from ..content_detection.request_text import UnreadableRequestError, credential_findings, request_text
from ..content_detection.scanner import DetectorSet, Segment
from ..content_detection.vocabulary import (
    DETECTOR_CREDENTIAL_ASSIGNMENT,
    DETECTOR_PROMPT_INJECTION,
    DETECTOR_SECRETS,
    SOURCE_PROMPT,
    SOURCE_TOOL_RESULT,
)
from ..content_security.handling import (
    ACTION_REFUSE,
    GATEWAY_KINDS,
    POLICY_PROMPT_INJECTION_REFUSED,
    POLICY_UNSCANNED_WITHHELD,
    REASON_GATEWAY_REFUSED,
    HandlingPlan,
)
from ..model_gateway.inbound.refusals import REASON_SECRET_DETECTED, InboundRefusal, refusal
from ..policy_engine.runtime import current_runtime
from .decision import (
    REASON_CONTENT_POLICY_DENIED,
    REASON_CONTENT_POLICY_UNAVAILABLE,
    REASON_SCAN_UNFINISHED,
    ContentDecision,
    ContentScans,
    content_detectors,
)
from .gateway_outcome import STAGE_CEDAR, STAGE_CONTENT, STAGE_TOOL_RESULT_POLICY, GatewayOutcome
from .obligations import Obligation, resolve

SOURCE_REQUEST = "request"
UNKNOWN_TOOL = "unknown"
METADATA_LIMIT = 10
#: What the person does next, for every coding agent (the refusal reaches Claude Code and Codex alike).
NEXT_STEP_HINT = ("Remove the affected message or start a new conversation (Claude Code: /rewind or /clear; Codex: "
                  "start a new session)")
DENIED_HINT = f"{NEXT_STEP_HINT}, or ask your Octryx administrator."
UNFINISHED_HINT = (f"This request is too large or dense to check in time, so it was not sent to the model. "
                   f"{NEXT_STEP_HINT}.")
UNAVAILABLE_HINT = ("The content policies cannot be evaluated right now, so a request with this data is not sent. "
                    "Try again later or ask your Octryx administrator.")


def _items(body: Mapping[str, Any], key: str) -> list[Any]:
    value = body.get(key)
    return value if isinstance(value, list) else []


def tool_results(body: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """``(tool name, result)`` of every tool result of ``body`` (see the module doc); the name is the calling
    item's ``name`` by its call id (``unknown`` when there is none)."""
    names: dict[str, str] = {}
    found: list[tuple[str, Any]] = []
    blocks = [block for message in _items(body, "messages") if isinstance(message, Mapping)
              for block in (message.get("content") if isinstance(message.get("content"), list) else [])]
    for item in [*blocks, *_items(body, "input")]:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type") if isinstance(item.get("type"), str) else ""
        call = item.get("id") if kind.endswith("tool_use") else item.get("call_id")
        if isinstance(call, str) and (kind.endswith("tool_use") or kind.endswith("_call")):
            names[call] = str(item.get("name") or kind.removesuffix("_call"))
        elif kind == "tool_result" or kind.endswith("_call_output"):
            call = item.get("tool_use_id") if kind == "tool_result" else item.get("call_id")
            found.append((names.get(call, UNKNOWN_TOOL) if isinstance(call, str) else UNKNOWN_TOOL, item))
    return found


def _assistant(item: Any) -> bool:
    return isinstance(item, Mapping) and (item.get("role") == "assistant" or (
        isinstance(item.get("type"), str) and item["type"].endswith("_call")))


def newest_turn(body: Mapping[str, Any]) -> Any:
    """What follows the last assistant message (or item) of ``body`` (a plain-text Responses input is all of it)."""
    if isinstance(body.get("input"), str):
        return body["input"]
    items = _items(body, "messages") or _items(body, "input")
    last = max((index for index, item in enumerate(items) if _assistant(item)), default=-1)
    return items[last + 1:]


@dataclass(frozen=True, slots=True)
class GatewayScan:
    """The passes over one request (see the module doc): the whole body (the gateway's built-in detectors, published
    and draft custom detectors), every tool's results (published, with prompt injection), the newest turn."""

    body: ContentScans
    tool_results: dict[str, Examination]
    newest: Examination

    @property
    def finished(self) -> bool:
        return (self.body.live.finished and self.body.draft.finished and self.newest.finished
                and all(item.finished for item in self.tool_results.values()))

    @property
    def injection(self) -> int:
        """How many prompt-injection findings the tool results carry."""
        return sum(item.report.counts().get(DETECTOR_PROMPT_INJECTION, 0) for item in self.tool_results.values())

    def secret_kinds(self) -> tuple[dict[str, str], ...]:
        """The credential kinds found (bounded, never a value): the run's timeline note."""
        kinds = dict.fromkeys(finding.kind or finding.detector for found in self.body.live.findings
                              for finding in found if finding.detector == DETECTOR_SECRETS)
        return tuple({"kind": kind, "source": SOURCE_REQUEST} for kind in list(kinds)[:METADATA_LIMIT])


def _with_fields(examination: Examination, text: str, value: Any, detectors: DetectorSet,
                 source: str) -> Examination:
    """``examination`` of ``text`` (``value`` serialized) plus its structured credential fields
    (``request_text.credential_findings``, the final check's classification too)."""
    if DETECTOR_CREDENTIAL_ASSIGNMENT not in detectors.builtin:
        return examination
    fields = credential_findings(text, examination.findings, value)
    return compose([examination, (source, fields)], domain=DOMAIN_TEXT) if fields else examination


def scan_request(body: Mapping[str, Any], workspace_id: str, budget: RequestBudget) -> GatewayScan:
    """The passes over ``body`` (see the module doc); raises ``request_text.UnreadableRequestError``."""
    custom, published = content_detectors(workspace_id)
    without = replace(custom, builtin=GATEWAY_KINDS)  # the gateway's built-in kinds only
    detectors = replace(custom, builtin=GATEWAY_KINDS | {DETECTOR_PROMPT_INJECTION})  # the tool-result pass
    text = request_text(body)
    whole = _with_fields(examine([Segment(text, SOURCE_REQUEST)], without, budget=budget), text, body, without,
                         SOURCE_REQUEST)
    results = tool_results(body)
    texts = [request_text(item) for _tool, item in results]
    each = examine_each([Segment(item, SOURCE_TOOL_RESULT) for item in texts], detectors, budget) if results else ()
    grouped: dict[str, list[Examination]] = {}
    for (tool, item), item_text, examination in zip(results, texts, each, strict=True):
        examination = _with_fields(examination, item_text, item, detectors, SOURCE_TOOL_RESULT)
        grouped.setdefault(tool, []).append(examination.restricted(published))
    turn = newest_turn(body)
    turn_text = request_text(turn)
    newest = _with_fields(examine([Segment(turn_text, SOURCE_PROMPT)], without, budget=budget), turn_text, turn,
                          without, SOURCE_PROMPT)
    return GatewayScan(ContentScans(whole.restricted(published), whole),
                       {tool: compose(items, domain=DOMAIN_TEXT) for tool, items in grouped.items()},
                       newest.restricted(published))


def forwarded_bytes(payload: Mapping[str, Any]) -> bytes:
    """The bytes sent upstream: the scanned payload, serialized (``gateway_plan.InboundPlan.payload``); raises
    ``request_text.UnreadableRequestError``."""
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise UnreadableRequestError("the request cannot be serialized") from None


def fixed_refusal(scan: GatewayScan, outcome: GatewayOutcome, finished: bool) -> InboundRefusal | None:
    """The fixed rules: an unfinished examination (``finished``: every pass finished and the deadline held after the
    last content work; its record states only the fixed disposition: no partial finding), then prompt injection in
    a tool result (the completed examination's findings are already on ``outcome``; the record adds the injection's
    count and source)."""
    if not finished:
        outcome.content = {"scanned": True, "complete": False, "unfinished": True}
        return outcome.refuse(refusal(STATE_DENIED, REASON_SCAN_UNFINISHED, http_status=400, hint=UNFINISHED_HINT),
                              STAGE_CONTENT, policies=(POLICY_UNSCANNED_WITHHELD,), fixed="unfinished")
    if not scan.injection:
        return None
    outcome.content = {**outcome.content, DETECTOR_PROMPT_INJECTION: {"count": scan.injection,
                                                                      "source": SOURCE_TOOL_RESULT}}
    return outcome.refuse(refusal(
        STATE_DENIED, REASON_CONTENT_POLICY_DENIED, http_status=403,
        hint=f"A tool result in this request tries to override instructions ({POLICY_PROMPT_INJECTION_REFUSED}). "
             f"{DENIED_HINT}"), STAGE_CONTENT, policies=(POLICY_PROMPT_INJECTION_REFUSED,), fixed="prompt_injection")


def handling_refusal(plan: HandlingPlan, outcome: GatewayOutcome) -> InboundRefusal | None:
    """A kind found that the plan refuses (``outcome.requested``) refuses the request."""
    refusing = sorted(kind for kind, action in outcome.requested.items() if action == ACTION_REFUSE)
    if not refusing:
        return None
    if DETECTOR_SECRETS in refusing:
        item = refusal(STATE_DENIED, REASON_SECRET_DETECTED, http_status=400,
                       hint=f"This request contains what looks like a secret; it was not sent to the model. "
                            f"{DENIED_HINT}")
    else:
        item = refusal(STATE_DENIED, REASON_CONTENT_POLICY_DENIED, http_status=403,
                       hint=f"Content handling {', '.join(plan.policies(refusing, ACTION_REFUSE))} refuses what was "
                            f"found. {DENIED_HINT}")
    return outcome.refuse(item, STAGE_CONTENT, policies=plan.policies(refusing, ACTION_REFUSE))


def tool_result_refusal(tool: str, reason: str, policies: tuple[str, ...], obligation: str,
                        outcome: GatewayOutcome) -> InboundRefusal:
    """A Workspace policy on a client tool's results (``client_tool_results``) refuses the whole request."""
    cedar = {"policies": list(policies), "obligation": obligation or "deny", "applied": ACTION_REFUSE, "tool": tool}
    if reason == REASON_CONTENT_POLICY_UNAVAILABLE:
        item = refusal(STATE_DENIED, reason, http_status=403, hint=UNAVAILABLE_HINT)
    else:
        item = refusal(STATE_DENIED, reason, http_status=403,
                       hint=f"Policy {', '.join(policies) or 'the content policy'} keeps results of the tool {tool} "
                            f"out of the model; on the gateway this request is refused. {DENIED_HINT}")
    return outcome.refuse(item, STAGE_TOOL_RESULT_POLICY, policies=policies, cedar=cedar)


def content_refusal(decision: ContentDecision, outcome: GatewayOutcome) -> InboundRefusal:
    """The Workspace's Cedar decision refusing (enforce, or unavailable). Deciding custom policies that carry a mask
    or reroute obligation are ``content_handling_gateway_refused`` (the gateway applies none); a plain block or a
    conflict is ``content_policy_denied``."""
    obligation = ""
    if decision.refusal != REASON_CONTENT_POLICY_UNAVAILABLE and decision.policies:
        runtime = current_runtime()
        resolved = resolve(decision.policies, runtime.custom_ids, runtime.custom_text)
        obligation = resolved.kind if isinstance(resolved, Obligation) else ""
    reason = decision.refusal if decision.refusal == REASON_CONTENT_POLICY_UNAVAILABLE else (
        REASON_GATEWAY_REFUSED if obligation else REASON_CONTENT_POLICY_DENIED)
    cedar = {"policies": list(decision.policies), "obligation": obligation or "deny", "applied": ACTION_REFUSE}
    if reason == REASON_CONTENT_POLICY_UNAVAILABLE:
        hint = UNAVAILABLE_HINT
    elif obligation:
        hint = (f"{decision.message()} The policy asks to mask or reroute; that applies only to the platform's own "
                f"model calls, so an external coding agent's request is refused. {DENIED_HINT}")
    else:
        hint = f"{decision.message()} {DENIED_HINT}"
    return outcome.refuse(refusal(STATE_DENIED, reason, http_status=403, hint=hint), STAGE_CEDAR,
                          policies=decision.policies, cedar=cedar)


__all__ = [
    "DENIED_HINT",
    "NEXT_STEP_HINT",
    "GatewayScan",
    "content_refusal",
    "fixed_refusal",
    "forwarded_bytes",
    "handling_refusal",
    "newest_turn",
    "scan_request",
    "tool_result_refusal",
    "tool_results",
]
