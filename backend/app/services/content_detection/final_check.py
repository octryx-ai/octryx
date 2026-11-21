"""The provider wrapper's final check: the final request object a driver hands to its transport or SDK, read once more.

Every driver's request passes here last (``content_security.model_call_outbound``): an HTTP driver's JSON body (the
bytes :func:`examine_request` returns are exactly the bytes sent, serialized inside the examination so the whole
check lies inside the call's deadline) and Bedrock's Converse arguments (the SDK's own serialization of the checked
object is a faithful encoding of it). The object must be valid Unicode text (checked before anything hashes it); its
full serialized size, opaque values included, is charged to the call's budget; it is read as **one text**
(``request_text``: its JSON serialization but the exact opaque key list), never rewritten, with the call's keep-out,
rerouting and reported kinds, plus its structured credential fields (``request_text.credential_findings``: the
same classification as the gateway's), and with the fixed prompt-injection rule. The only text not read is a string
value that is exactly a shipped seed text (``prompt_catalog.shipped_seed_text``, by content hash: the whole field,
never a part of one). The one exemption, by field identity: prompt injection is not evaluated in a system carrier
of the driver's request (:func:`_injection_view`: the top-level ``system`` or ``systemInstruction``, and the
``content`` of a message of the top-level ``messages`` or ``input`` list whose ``role`` is the string ``system`` or
``developer``; as text or as text blocks) whose value is exactly one of this call's administrator-authored system
texts (:attr:`FinalCheck.authored`, as sent) or exactly the drivers' join of the call's system texts
(:attr:`FinalCheck.system`, :data:`SYSTEM_JOIN`: one value for all of them, Google's ``systemInstruction``) — the
join's other system texts are evaluated on their own —; nothing else of the request (tool definitions and tool data
included) is looked at for a role, every other detector reads it, and the same text in any other field, or inside a
longer value, is evaluated. After all of this one reading of the call's
clock decides whether the examination finished. The request is refused, typed (:class:`FinalCheckRefused`), and
nothing is sent when:

- prompt injection, or a kind whose applied action must keep it out (:attr:`FinalCheck.keep_out`: ``refuse``,
  ``mask``, ``mask_reroute``), is present (``content_final_check_refused``);
- a rerouting kind (:attr:`FinalCheck.route_kinds`) is present and the call is not going to the Workspace's
  governance alias (:attr:`FinalCheck.routed`) (``content_route_unavailable``);
- the examination is unfinished, the object is larger than the budget's cap, or the call's budget was spent
  (``content_scan_unfinished``);
- the object cannot be read as JSON text or carries text that is not valid Unicode (``content_unreadable``).

A check that passes calls :attr:`FinalCheck.passed` with its examination of what is sent (the text findings and the
structured credential fields): the request is handed to the transport, and the call's one record is derived from that
examination (``content_security.model_call_outcome``).
"""

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
    """The final check refused the request: nothing was sent. ``kinds``: what was present."""

    def __init__(self, reason: str, kinds: frozenset[str] = frozenset()) -> None:
        self.reason = reason
        self.kinds = kinds
        super().__init__(f"the final check refused the request: {reason}")


def _nothing(_sent: Examination) -> None:
    return None


@dataclass(frozen=True, slots=True)
class FinalCheck:
    """What the final check of one call enforces (see the module doc)."""

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

    def exempt(self, value: str) -> bool:
        """A system field's ``value`` is exactly an authored system text, or exactly the join of the system texts:
        injection is not evaluated in it (the join's other texts are, :meth:`unexempt`)."""
        return bool(self.authored) and (value in self.authored or value == SYSTEM_JOIN.join(self.system))

    def unexempt(self) -> list[str]:
        """The system texts that are not authored: injection is evaluated in them wherever they are sent."""
        return [item for item in self.system if item not in self.authored] if self.authored else []


def _system(item: Any) -> bool:
    return isinstance(item, Mapping) and isinstance(item.get("role"), str) and item["role"] in SYSTEM_ROLES


def _injection_view(payload: Any, exempt: Callable[[str], bool]) -> Any:
    """``payload`` with every system carrier (see the module doc) whose text ``exempt`` names read as empty: what the
    prompt-injection detector reads (a copy; the request is not changed). Only the carrier positions are looked at."""
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
    """``payload`` (the final request object) under ``check``: its bytes exactly as they are sent (UTF-8 JSON);
    raises :class:`FinalCheckRefused`."""
    budget = check.budget
    if budget.overrun:
        raise FinalCheckRefused(REASON_UNFINISHED)
    if not utf8_clean(payload):
        raise FinalCheckRefused(REASON_UNREADABLE)
    try:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
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
