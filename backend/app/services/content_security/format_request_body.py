"""An external coding agent's request body (Anthropic Messages or Responses input): where its newest turn and tool
results are, one detector pass that answers for each of them, and the masking of the body before it is sent."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ..content_detection.examination import DOMAIN_TEXT, Examination, RequestBudget, compose, examine
from ..content_detection.platform_detectors import credential_field
from ..content_detection.request_examination import RequestExaminer, strict_json
from ..content_detection.request_spans import SpannedText, spanned_text
from ..content_detection.request_text import UnreadableRequestError, credential_findings, opaque
from ..content_detection.scanner import DetectorSet, Segment
from ..content_detection.vocabulary import (
    DETECTOR_CREDENTIAL_ASSIGNMENT,
    DETECTOR_PROMPT_INJECTION,
    DETECTOR_SECRETS,
    SOURCE_PROMPT,
    SOURCE_TOOL_RESULT,
)
from ..content_routing.decision import (
    ContentScans,
    content_detectors,
)
from .handling import SURFACE_GATEWAY, shipped_plan
from .model_call_masking import credential_finding
from .transport import TransportRun

#: The kinds the shipped defaults act on (a Workspace's plan names its own).
SHIPPED_ACTING = shipped_plan(SURFACE_GATEWAY).acting
#: Keys whose value is the body's structure (model, discriminators, call ids that pair a call with its result).
_STRUCTURE = frozenset({"model", "type", "role", "id", "call_id", "tool_use_id", "stream", "cache_control"})


@dataclass(frozen=True, slots=True)
class MaskedBody:
    body: dict[str, Any]
    masked: int
    withheld: int


def _walk(run: TransportRun, holder: Mapping[str, Any], key: Any, value: Any) -> Any:
    if isinstance(value, dict):
        return {name: _walk(run, value, name, item) for name, item in value.items()}
    if isinstance(value, list):
        return [_walk(run, holder, key, item) for item in value]
    if not isinstance(value, str) or not value or key in _STRUCTURE or opaque(holder, key, value):
        return value
    if isinstance(key, str) and credential_field(key, value):
        whole = run.whole(value, credential_finding(value))
        return whole if whole != value else run.text(value)
    embedded = _embedded(value)
    if embedded is not None:  # JSON in a string (call arguments, a tool result): its fields, re-serialized if changed
        masked = _walk(run, {}, None, embedded)
        return value if masked == embedded else json.dumps(masked, ensure_ascii=False)
    return run.text(value)


def _embedded(value: str) -> dict[str, Any] | list[Any] | None:
    if not value.lstrip().startswith(("{", "[")):
        return None
    try:
        parsed = strict_json(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict | list) else None


def mask_gateway_body(body: Mapping[str, Any], detectors: DetectorSet, mask: frozenset[str],
                      budget: RequestBudget) -> MaskedBody:
    run = TransportRun(RequestExaminer(detectors, budget), mask)
    masked = {key: _walk(run, body, key, value) for key, value in body.items()}
    return MaskedBody(masked, run.masked, run.withheld)


SOURCE_REQUEST = "request"


UNKNOWN_TOOL = "unknown"


METADATA_LIMIT = 10


def _items(body: Mapping[str, Any], key: str) -> list[Any]:
    value = body.get(key)
    return value if isinstance(value, list) else []


# The tool name is the calling item's by its call id, ``unknown`` when there is none.
def tool_results(body: Mapping[str, Any]) -> list[tuple[str, Any]]:
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
    if isinstance(body.get("input"), str):
        return body["input"]
    items = _items(body, "messages") or _items(body, "input")
    last = max((index for index, item in enumerate(items) if _assistant(item)), default=-1)
    return items[last + 1:]


def _result(item: Any) -> bool:
    kind = item.get("type") if isinstance(item, Mapping) else None
    return isinstance(kind, str) and (kind == "tool_result" or kind.endswith("_call_output"))


def _turn_results(turn: Any) -> set[int]:
    items = turn if isinstance(turn, list) else []
    blocks = [block for item in items if isinstance(item, Mapping) and isinstance(item.get("content"), list)
              for block in item["content"]]
    return {id(item) for item in [*items, *blocks] if _result(item)}


@dataclass(frozen=True, slots=True)
class GatewayScan:
    body: ContentScans
    tool_results: dict[str, Examination]
    newest: Examination
    prompt: Examination  # injection in the newest turn's own text
    new_results: tuple[Examination, ...] = ()  # the newest turn's tool results, the ones injection refuses

    @property
    def finished(self) -> bool:
        return (self.body.live.finished and self.body.draft.finished and self.newest.finished
                and self.prompt.finished and all(item.finished for item in self.tool_results.values()))

    @property
    def injection(self) -> int:
        return sum(item.report.counts().get(DETECTOR_PROMPT_INJECTION, 0)
                   for item in (*self.new_results, self.prompt))

    def secret_kinds(self) -> tuple[dict[str, str], ...]:
        kinds = dict.fromkeys(finding.kind or finding.detector for found in self.body.live.findings
                              for finding in found if finding.detector == DETECTOR_SECRETS)
        return tuple({"kind": kind, "source": SOURCE_REQUEST} for kind in list(kinds)[:METADATA_LIMIT])


def _with_fields(examination: Examination, text: str, value: Any, detectors: DetectorSet,
                 source: str) -> Examination:
    if DETECTOR_CREDENTIAL_ASSIGNMENT not in detectors.builtin:
        return examination
    fields = credential_findings(text, examination.findings, value)
    return compose([examination, (source, fields)], domain=DOMAIN_TEXT) if fields else examination


# One detector pass over the request's text; each part's view is read from it as if the part had been examined alone.
# Injection is read in the newest turn and its tool results: a client's own system prompt and the older turns and
# results it re-sends were admitted before, so refusing them again would end the conversation for good.
def examine_request_body(body: Mapping[str, Any], workspace_id: str, budget: RequestBudget,
                 acting: frozenset[str] = SHIPPED_ACTING) -> GatewayScan:
    custom, published = content_detectors(workspace_id)
    without = replace(custom, builtin=acting - {DETECTOR_PROMPT_INJECTION})
    detectors = replace(custom, builtin=without.builtin | {DETECTOR_PROMPT_INJECTION})
    results = tool_results(body)
    turn = newest_turn(body)
    parts = {id(item) for _tool, item in results} | ({id(item) for item in turn} if isinstance(turn, list) else set())
    spanned = spanned_text(body, lambda part: id(part) in parts)
    one = examine([Segment(spanned.text, SOURCE_REQUEST)], detectors, budget=budget)
    whole = _with_fields(one.restricted(without.ids()), spanned.text, body, without, SOURCE_REQUEST)
    new = _turn_results(turn)
    grouped: dict[str, list[Examination]] = {}
    new_results: list[Examination] = []
    for tool, item in results:
        start, end = _span(spanned, item)
        examination = _with_fields(one.within(start, end, SOURCE_TOOL_RESULT), spanned.text[start:end], item,
                                   detectors, SOURCE_TOOL_RESULT)
        grouped.setdefault(tool, []).append(examination.restricted(published))
        if id(item) in new:
            new_results.append(examination)
    newest, prompt = _turn_views(spanned, one, turn, new, without)
    return GatewayScan(ContentScans(whole.restricted(published), whole),
                       {tool: compose(items, domain=DOMAIN_TEXT) for tool, items in grouped.items()},
                       newest.restricted(published), prompt, tuple(new_results))


def _span(spanned: SpannedText, part: Any) -> tuple[int, int]:
    found = spanned.span(part)
    if found is None:
        raise UnreadableRequestError("a part of the request has no place in its text")
    return found


# The newest turn as request_text(turn) reads it (a list slice gets its brackets), and injection in its own text, its
# tool results left out (they are read on their own).
def _turn_views(spanned: SpannedText, one: Examination, turn: Any, results: set[int],
                without: DetectorSet) -> tuple[Examination, Examination]:
    if isinstance(turn, list):
        spans = [_span(spanned, item) for item in turn]
        start, end = (spans[0][0], spans[-1][1]) if spans else (0, 0)
        padding, text = 1, "[" + spanned.text[start:end] + "]"
        skipped = [_span(spanned, item) for item in _result_parts(turn) if id(item) in results]
    else:
        start, end = spanned.top.get("input", (0, 0))
        padding, text, skipped = 0, spanned.text[start:end], []
    view = one.within(start, end, SOURCE_PROMPT, padding=padding)
    newest = _with_fields(view.restricted(without.ids()), text, turn, without, SOURCE_PROMPT)
    own = one.excluding(lambda _index, item: any(a <= item.start and item.end <= b for a, b in skipped))
    prompt = own.within(start, end, SOURCE_PROMPT, padding=padding).restricted(frozenset({DETECTOR_PROMPT_INJECTION}))
    return newest, prompt


def _result_parts(turn: list[Any]) -> list[Any]:
    blocks = [block for item in turn if isinstance(item, Mapping) and isinstance(item.get("content"), list)
              for block in item["content"]]
    return [item for item in [*turn, *blocks] if _result(item)]


def forwarded_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise UnreadableRequestError("the request cannot be serialized") from None


__all__ = ["SHIPPED_ACTING", "SOURCE_REQUEST", "GatewayScan", "MaskedBody", "examine_request_body", "forwarded_bytes",
           "mask_gateway_body", "newest_turn", "tool_results"]
