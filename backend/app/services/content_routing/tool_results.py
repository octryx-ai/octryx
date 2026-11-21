"""The tool-result check: a tool result is scanned and decided before it enters a model's context.

``receive_tool_result`` is asked with the tool (``Tool::"<name>"``, its connector family as parent; a coding
agent's own tool is ``Tool::"client:<name>"``), its origin (``connector``, ``mcp``, ``client``) and what the scan
found. The baseline grants (``platform:tool-result-permit``); content policies narrow it:

- a plain block replaces the result with a refusal the model reads (``content_policy_denied``), in enforce mode;
- a ``mask`` obligation masks the findings it names in every string of the result and asks again
  (``content_obligation_insufficient`` when the masked result is still denied); tool results are never routed;
- shadow: the result goes on unchanged and its record says what would happen (``cedar.would``);
- in every mode, a part the scan does not finish (a string whose scan is unfinished, more strings than
  :data:`MAX_STRINGS`, a part deeper than :data:`MAX_DEPTH`) is withheld (``masking.WITHHELD_TEXT``) before
  the decision, and the outcome says how many (``withheld``); a result whose parts finish one by one but not
  together is blocked (``content_scan_unfinished``). Nothing unexamined enters a context or leaves to an MCP
  client.

Before the custom policies, the Workspace's content handling (``tool_result_handling``): a kind it refuses blocks the
result (``content_policy_denied``); ``report`` is informational; mask and reroute apply where the result next reaches
a model. Each record names the requested and the applied action per kind.

Each check has at most one decision record (``tool_result_handling.ToolResultHandling``), written once when the
check returns the result to its caller, from what was actually released and the kinds the released result carries
(Cedar's comparison writes none of its own here); a check that fails or is cancelled before that writes nothing. A
coding agent's own tool whose output the launcher cannot replace (``client_keeps``) keeps it unchanged whatever was
decided — blocked, masked or with parts withheld —: its record and notice say ``kept_by_client`` and claim no block,
mask or withhold. Only what entered the context is remembered for the conversation, after the record: the masked
result's findings for a mask, nothing for a block, the original for a result the client keeps. The outcome carries a
notice (detector × count, policy, the record) for the user — never the data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from ..content_detection.examination import examine_text
from ..content_detection.masking import WITHHELD_TEXT
from ..content_detection.registry import combined_definitions, detector_set_for
from ..content_detection.scanner import ScanReport, Segment
from ..content_detection.vocabulary import SOURCE_TOOL_RESULT
from ..content_security.handling import (
    PLATFORM_SESSION_WITHOUT_WORKSPACE,
    REASON_HANDLING_UNAVAILABLE,
    SURFACE_PLATFORM,
    ContentHandlingUnavailableError,
    PlatformScope,
    content_handling_isolated,
)
from ..policy_engine.runtime import MODE_ENFORCE, current_runtime
from .body_masking import MaskRun
from .conversation_state import load_state, remember
from .decision import (
    REASON_CONTENT_POLICY_DENIED,
    REASON_SCAN_UNFINISHED,
    ContentDecision,
    decide_tool_result,
    scan_for,
)
from .obligations import REASON_INSUFFICIENT, Obligation, Unresolved, resolve
from .tool_result_handling import (
    RELEASED_BLOCKED,
    RELEASED_KEPT_BY_CLIENT,
    RELEASED_MASKED,
    RELEASED_UNCHANGED,
    ToolResultHandling,
    apply_plan,
    tool_result_record,
)

MAX_STRINGS = 5000
MAX_DEPTH = 12


@dataclass(frozen=True, slots=True)
class ToolResultOutcome:
    result: Any
    blocked: bool = False
    reason: str = ""
    notice: Mapping[str, Any] = field(default_factory=dict)


def _strings(value: Any, depth: int = 0, out: list[str | None] | None = None) -> list[str | None]:
    """Every string of ``value``, up to :data:`MAX_STRINGS`; a deeper part than :data:`MAX_DEPTH` adds ``None``
    (not read: the scan is incomplete, and the masked result withholds that part)."""
    out = [] if out is None else out
    if len(out) >= MAX_STRINGS:
        return out
    if depth > MAX_DEPTH:
        if isinstance(value, str | Mapping | list | tuple):
            out.append(None)
        return out
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            _strings(item, depth + 1, out)
    elif isinstance(value, list | tuple):
        for item in value:
            _strings(item, depth + 1, out)
    return out


def _segments(result: Any) -> list[Segment]:
    strings = _strings(result)
    segments = [Segment(text, SOURCE_TOOL_RESULT) for text in strings if text]
    if None in strings:
        segments.append(Segment("", SOURCE_TOOL_RESULT, readable=False))  # too deep to read: incomplete
    if len(strings) >= MAX_STRINGS:
        segments.append(Segment("", SOURCE_TOOL_RESULT, readable=False))  # too large to read: incomplete
    return segments


def _masked(value: Any, apply, depth: int = 0) -> Any:
    """Every string of ``value`` through ``apply``; a part deeper than :data:`MAX_DEPTH` was never read, so it is
    withheld instead of passed on."""
    if depth > MAX_DEPTH and isinstance(value, str | Mapping | list | tuple):
        return WITHHELD_TEXT
    if isinstance(value, str):
        return apply(value)
    if isinstance(value, Mapping):
        return {key: _masked(item, apply, depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_masked(item, apply, depth + 1) for item in value]
    return value


def _overflows(strings: list[str | None]) -> bool:
    return None in strings or len(strings) >= MAX_STRINGS


def _withheld(result: Any, workspace_id: str | None) -> tuple[Any, int]:
    """``result`` with every part the scan does not finish withheld: strings past :data:`MAX_STRINGS`, parts deeper
    than :data:`MAX_DEPTH`, and each string whose own scan is unfinished (new containers; the input is unchanged)."""
    runtime = current_runtime()
    detectors = detector_set_for(combined_definitions(runtime.custom_detectors, runtime.draft_detectors),
                                 workspace_id)
    counts = {"strings": 0, "withheld": 0}

    def withhold() -> str:
        counts["withheld"] += 1
        return WITHHELD_TEXT

    def walk(value: Any, depth: int) -> Any:
        if depth > MAX_DEPTH and isinstance(value, str | Mapping | list | tuple):
            return withhold()
        if isinstance(value, str):
            counts["strings"] += 1
            if counts["strings"] > MAX_STRINGS or (
                    value and not examine_text(value, SOURCE_TOOL_RESULT, detectors).finished):
                return withhold()
            return value
        if isinstance(value, Mapping):
            return {key: walk(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [walk(item, depth + 1) for item in value]
        return value

    return walk(result, 0), counts["withheld"]


def _decide(result: Any, request: Mapping[str, Any], sensitive: frozenset[str]) -> ContentDecision:
    scans = scan_for(_segments(result), request["workspace_id"])
    return decide_tool_result(scans=scans, sensitive=sensitive, **request)


def _notice(decision: ContentDecision, *, kind: str, policies: Iterable[str], masked: int = 0,
            reason: str = "") -> dict[str, Any]:
    """The notice; ``decision_id`` names the check's one record once it is released (:func:`check_tool_result`). An
    unfinished examination's notice is the fixed one: no finding-derived count."""
    found = {} if reason == REASON_SCAN_UNFINISHED else decision.report.counts()
    return {"kind": kind, "found": found, "masked": masked, "policies": list(policies),
            "decision_id": None, "reason": reason or "content_obligation_applied"}


def blocked_payload(tool_name: str, notice: Mapping[str, Any]) -> dict[str, Any]:
    found = ", ".join(f"{key} ×{count}" for key, count in dict(notice.get("found") or {}).items())
    names = ", ".join(notice.get("policies") or []) or "a content policy"
    return {"error": f"Octryx blocked this tool result: it contains {found or 'sensitive data'} and the "
                     f"policy {names} does not allow it into the conversation. Use a governed tool that returns "
                     "masked data, or ask an administrator.",
            "error_category": "policy_denied", "reason": notice.get("reason") or REASON_CONTENT_POLICY_DENIED,
            "content_policy": dict(notice), "tool": tool_name}


Badge = ScanReport | None  # what entered the context (the conversation's badge), counted after the release

async def check_tool_result(
    result: Any, *, tool_name: str, family: str | None, origin: str, workspace_id: str | None,
    session_id: str | None, conversation: str, connections: Iterable[str] = (), principal: Any = None,
    classification: Any = None, client_keeps: bool = False,
) -> ToolResultOutcome:
    """The tool result as released. Its one record is written once the result is decided (a check failing or
    cancelled before that writes none), then the conversation's badge is counted (in its own session) and the result
    is returned.
    ``client_keeps``: the caller cannot replace the output (a coding agent's own built-in tool,
    ``client_tool_results``): whatever was decided, the client keeps it unchanged and the record says so
    (``kept_by_client``)."""
    request = {"tool_name": tool_name, "family": family, "origin": origin, "workspace_id": workspace_id,
               "classification": classification, "connections": tuple(connections), "principal": principal}
    record = tool_result_record(tool_name=tool_name, workspace_id=workspace_id, session_id=session_id,
                                principal=principal[0].label() if principal else "system")
    state = await load_state(session_id, conversation)
    outcome, badge = await _checked(result, request, record, state.categories)
    if client_keeps and (outcome.blocked or record.released == RELEASED_MASKED or record.withheld):
        # The client keeps its output as it is: nothing was blocked, masked or withheld, and the badge counts what
        # entered the context — the original.
        badge = _decide(result, request, state.categories).report
        record.release(RELEASED_KEPT_BY_CLIENT, outcome.reason or record.released, present=badge.detected)
        outcome = replace(outcome, notice={**outcome.notice, "kept_by_client": True})
    if outcome.notice and record.stated:
        outcome = replace(outcome, notice={**outcome.notice, "decision_id": record.decision_id})
    record.write()
    if badge is not None:  # only what entered the context, after the record
        await remember(session_id, conversation, badge)
    return outcome


def _blocked(record: ToolResultHandling, tool_name: str, notice: dict[str, Any], reason: str,
             cedar: dict[str, Any] | None = None) -> tuple[ToolResultOutcome, Badge]:
    record.release(RELEASED_BLOCKED, reason, cedar=cedar)
    return ToolResultOutcome(blocked_payload(tool_name, notice), True, reason, notice), None


async def _checked(result: Any, request: Mapping[str, Any], record: ToolResultHandling,
                   sensitive: frozenset[str]) -> tuple[ToolResultOutcome, Badge]:
    tool_name = str(request["tool_name"])
    # A result too large or too deep to read is unfinished (C12B-04): withheld before any decision is asked.
    first = None if _overflows(_strings(result)) else _decide(result, request, sensitive)
    if first is None or not first.scans.live.finished:
        result, record.withheld = _withheld(result, request["workspace_id"])
        first = _decide(result, request, sensitive)
    if not first.scans.live.finished:  # the parts finish one by one but not together: nothing unread goes on
        notice = _notice(first, kind="block", policies=(), reason=REASON_SCAN_UNFINISHED)
        return _blocked(record, tool_name, notice, REASON_SCAN_UNFINISHED)
    try:
        # A turn without a Workspace is a session without one by design (``handling.PlatformScope``).
        plan = await content_handling_isolated(request["workspace_id"] or PlatformScope(
            PLATFORM_SESSION_WITHOUT_WORKSPACE), SURFACE_PLATFORM)
    except ContentHandlingUnavailableError:
        notice = _notice(first, kind="block", policies=(), reason=REASON_HANDLING_UNAVAILABLE)
        return _blocked(record, tool_name, notice, REASON_HANDLING_UNAVAILABLE)
    apply_plan(record, plan, first.scans.live.detected, first.report.counts())
    if record.refused:
        notice = _notice(first, kind="block", policies=record.refused, reason=REASON_CONTENT_POLICY_DENIED)
        return _blocked(record, tool_name, notice, REASON_CONTENT_POLICY_DENIED)
    return await _released(result, request, first, record, sensitive)


async def _released(result: Any, request: Mapping[str, Any], first: ContentDecision, record: ToolResultHandling,
                    sensitive: frozenset[str]) -> tuple[ToolResultOutcome, Badge]:
    """The Workspace's Cedar decision: the result as it is released."""
    tool_name = str(request["tool_name"])
    comparison = first.comparison
    denied = comparison is not None and comparison.cedar_allowed is False and not comparison.errors
    runtime = current_runtime()
    if not denied:
        if first.refusal:  # the engine cannot answer while a published policy names a finding (fail closed)
            notice = _notice(first, kind="block", policies=(), reason=first.refusal)
            return _blocked(record, tool_name, notice, first.refusal)
        record.release(RELEASED_UNCHANGED, present=first.scans.live.detected)
        return _allowed(result, record.withheld), first.report
    resolved = resolve(comparison.determining, runtime.custom_ids, runtime.custom_text, tool_result=True)
    if runtime.mode != MODE_ENFORCE:
        would = {"policies": list(resolved.policies), "would": "deny", "applied": "none"}
        if isinstance(resolved, Obligation):
            would.update({"obligation": resolved.kind, "mask": sorted(resolved.mask)})
        record.release(RELEASED_UNCHANGED, cedar=would, present=first.scans.live.detected)
        return _allowed(result, record.withheld), first.report
    if isinstance(resolved, Unresolved):
        notice = _notice(first, kind="block", policies=resolved.policies, reason=resolved.reason)
        return _blocked(record, tool_name, notice, resolved.reason,
                        cedar={"policies": list(resolved.policies), "decision": "deny"})
    outcome, badge = await _mask(result, request, first, resolved, sensitive, record)
    if record.withheld and not outcome.blocked:
        return replace(outcome, notice={**outcome.notice, "withheld": record.withheld}), badge
    return outcome, badge


def _allowed(result: Any, withheld: int) -> ToolResultOutcome:
    """An allowed result; a result with withheld parts says so (``withheld``: count, never the data)."""
    if not withheld:
        return ToolResultOutcome(result)
    return ToolResultOutcome(result, notice={"kind": "withhold", "found": {}, "masked": 0, "withheld": withheld,
                                             "policies": [], "decision_id": None, "reason": REASON_SCAN_UNFINISHED})


async def _mask(result: Any, request: Mapping[str, Any], first: ContentDecision, obligation: Obligation,
                sensitive: frozenset[str], record: ToolResultHandling) -> tuple[ToolResultOutcome, Badge]:
    detectors = detector_set_for(current_runtime().custom_detectors, request["workspace_id"])
    run = MaskRun(detectors, obligation.mask, obligation.mask_style)  # one numbering for the whole result
    masked_result = _masked(result, run.text)  # new containers; the input is never changed
    second = _decide(masked_result, request, sensitive)
    cedar = {"policies": list(obligation.policies), "decision": "deny", "obligation": obligation.kind,
             "mask": sorted(obligation.mask), "mask_style": obligation.mask_style, "masked": run.masked}
    # Only an answered allow lets the masked result in (an unanswered engine must not let it pass).
    if not second.allowed or second.comparison is None or second.comparison.cedar_allowed is not True:
        reason = REASON_SCAN_UNFINISHED if not second.scans.live.finished else REASON_INSUFFICIENT
        policies = second.comparison.determining if second.comparison else obligation.policies
        notice = _notice(first, kind="block", policies=policies, reason=reason)
        return _blocked(record, str(request["tool_name"]), notice, reason,
                        cedar={**cedar, "second_decision": "deny"})
    record.release(RELEASED_MASKED, cedar={**cedar, "second_decision": "allow"}, present=second.scans.live.detected)
    notice = _notice(first, kind="mask", policies=obligation.policies, masked=run.masked)
    return ToolResultOutcome(masked_result, False, "", notice), second.report


__all__ = ["ToolResultOutcome", "blocked_payload", "check_tool_result"]
