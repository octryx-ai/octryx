"""The provider wrapper's final check of the request object a driver hands to its transport or SDK."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..prompt_catalog import shipped_seed_text
from .examination import DOMAIN_TEXT, Examination, RequestBudget, compose, examine_pass
from .request_examination import utf8_clean
from .request_text import UnreadableRequestError, credential_findings, request_text
from .scanner import DetectorSet
from .vocabulary import DETECTOR_CREDENTIAL_ASSIGNMENT, DETECTOR_PROMPT_INJECTION

REASON_FINAL_CHECK = "content_final_check_refused"
REASON_ROUTE = "content_route_unavailable"
REASON_UNFINISHED = "content_scan_unfinished"
REASON_UNREADABLE = "content_unreadable"
SOURCE_REQUEST = "request"
#: How the drivers that send several system texts as one value join them (Google's ``systemInstruction``).
SYSTEM_JOIN = "\n\n"
SYSTEM_ROLES = frozenset({"system", "developer"})
SYSTEM_KEYS = ("system", "systemInstruction")  # top-level system fields (Anthropic and Bedrock, Google)
MESSAGE_KEYS = ("messages", "input")  # top-level message lists (chat completions, Bedrock, Ollama; Responses)
_INJECTION = DetectorSet(builtin=frozenset({DETECTOR_PROMPT_INJECTION}))


class FinalCheckRefused(Exception):  # noqa: N818 - a refusal, raised to stop the send
    def __init__(self, reason: str, kinds: frozenset[str] = frozenset()) -> None:
        self.reason = reason
        self.kinds = kinds
        super().__init__(f"the final check refused the request: {reason}")


def _nothing(_sent: Examination) -> None:
    return None


@dataclass(frozen=True, slots=True)
class FinalCheck:
    keep_out: frozenset[str]
    budget: RequestBudget
    route_kinds: frozenset[str] = frozenset()
    routed: bool = False  # the call goes to the Workspace's governance alias
    reported: frozenset[str] = frozenset()  # kinds read only to state whether the sent bytes carry them
    authored: tuple[str, ...] = ()  # the call's authored system texts, as sent
    system: tuple[str, ...] = ()  # all of the call's system texts, as sent, in order
    passed: Callable[[Examination], None] = _nothing  # handed to the transport, with what the sent bytes carry

    @property
    def detectors(self) -> DetectorSet:
        return DetectorSet(builtin=self.keep_out | self.route_kinds | self.reported)

    # Only a whole value counts: an authored text inside a longer value, or in any other field, is evaluated.
    def exempt(self, value: str) -> bool:
        return bool(self.authored) and (value in self.authored or value == SYSTEM_JOIN.join(self.system))

    def unexempt(self) -> list[str]:
        return [item for item in self.system if item not in self.authored] if self.authored else []


def _system(item: Any) -> bool:
    return isinstance(item, Mapping) and isinstance(item.get("role"), str) and item["role"] in SYSTEM_ROLES


# A copy for the injection detector: only the system carrier positions are looked at, the request is not changed.
def _injection_view(payload: Any, exempt: Callable[[str], bool]) -> Any:
    def texts(value: Any) -> Any:
        if isinstance(value, str):
            return "" if exempt(value) else value
        if isinstance(value, list):
            return [{**item, "text": ""} if isinstance(item, Mapping) and isinstance(item.get("text"), str)
                    and exempt(item["text"]) else item for item in value]
        if isinstance(value, Mapping) and isinstance(value.get("parts"), list):
            return {**value, "parts": texts(value["parts"])}
        return value

    if not isinstance(payload, Mapping):
        return payload
    read = dict(payload)
    for key in SYSTEM_KEYS:
        if key in payload:
            read[key] = texts(payload[key])
    for key in MESSAGE_KEYS:
        if isinstance(payload.get(key), list):
            read[key] = [{**item, "content": texts(item["content"])} if _system(item) and "content" in item else item
                         for item in payload[key]]
    return read


def _unfinished(budget: RequestBudget) -> FinalCheckRefused:
    budget.charge(chars=budget.max_chars + 1)  # the request stays unfinished
    return FinalCheckRefused(REASON_UNFINISHED)


def examine_request(check: FinalCheck, payload: Any) -> bytes:
    budget = check.budget
    if budget.overrun:
        raise FinalCheckRefused(REASON_UNFINISHED)
    if not utf8_clean(payload):
        raise FinalCheckRefused(REASON_UNREADABLE)
    try:
        # Serialized inside the examination: these are exactly the bytes sent, and the work counts against the deadline.
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        # Read as one text and never rewritten; only a value that is exactly a shipped seed text is skipped.
        text = request_text(payload, shipped_seed_text)
        injection_text = request_text([_injection_view(payload, check.exempt), check.unexempt()],
                                      shipped_seed_text) if check.authored else text
    except (TypeError, ValueError, RecursionError, UnreadableRequestError):
        raise FinalCheckRefused(REASON_UNREADABLE) from None
    if len(body) > budget.max_chars:  # the full serialized size, opaque values included
        raise _unfinished(budget)
    kinds = examine_pass(text, SOURCE_REQUEST, check.detectors, budget)
    fields = credential_findings(text, kinds.findings, payload, shipped_seed_text) if (
        DETECTOR_CREDENTIAL_ASSIGNMENT in check.detectors.builtin) else ()
    injection = examine_pass(injection_text, SOURCE_REQUEST, _INJECTION, budget)
    if not (kinds.finished and injection.finished) or budget.overrun:  # one clock reading after all content work
        raise _unfinished(budget)
    sent = compose([kinds, (SOURCE_REQUEST, fields)], domain=DOMAIN_TEXT)
    refused = sent.detected & check.keep_out | injection.detected
    if refused:
        raise FinalCheckRefused(REASON_FINAL_CHECK, frozenset(refused))
    if sent.detected & check.route_kinds and not check.routed:
        raise FinalCheckRefused(REASON_ROUTE, frozenset(sent.detected & check.route_kinds))
    check.passed(sent)
    return body


__all__ = [
    "REASON_FINAL_CHECK",
    "REASON_ROUTE",
    "REASON_UNFINISHED",
    "REASON_UNREADABLE",
    "SYSTEM_JOIN",
    "FinalCheck",
    "FinalCheckRefused",
    "examine_request",
]
