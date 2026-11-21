"""The structured analysis: parse, validate, check citations, render.

``parse_analysis`` accepts exactly the ``incident_analysis_v1`` JSON object (an optional ```json fence is
tolerated) and refuses anything else with a closed code (``analysis_not_json``, ``analysis_invalid``). Strings
are bounded, lists are capped, unknown keys are dropped.

``check_citations`` marks every evidence entry and similar ticket ``verified`` only when its locator, url or
key appears in what the tools actually returned in this run; an analysis whose evidence is all unverified is
``analysis_uncited``. Nothing a model claims to have read is stored as verified unless a tool showed it.

``render_note`` is the plain-text/markdown note stored on the Work Item.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

CONFIDENCE = ("low", "medium", "high")
SOURCE_KINDS = ("manual", "config", "repository", "ticket", "knowledge")
MAX_TEXT = 2000
MAX_SHORT = 400
MAX_ITEMS = 12
MAX_NOTE_CHARS = 12000

CODE_NOT_JSON = "analysis_not_json"
CODE_INVALID = "analysis_invalid"
CODE_UNCITED = "analysis_uncited"
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class AnalysisContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _text(value: Any, limit: int = MAX_TEXT, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise AnalysisContractError(CODE_INVALID)
    return value.strip()[:limit]


def _optional_text(value: Any, limit: int = MAX_SHORT) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AnalysisContractError(CODE_INVALID)
    return value.strip()[:limit] or None


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnalysisContractError(CODE_INVALID)
    return value[:MAX_ITEMS]


def _strings(value: Any) -> list[str]:
    return [text for text in (_text(entry, MAX_SHORT) for entry in _list(value)) if text]


def _evidence(value: Any) -> list[dict[str, Any]]:
    entries = []
    for entry in _list(value):
        if not isinstance(entry, dict) or not isinstance(entry.get("source"), dict):
            raise AnalysisContractError(CODE_INVALID)
        source = entry["source"]
        kind = source.get("kind")
        if kind not in SOURCE_KINDS:
            raise AnalysisContractError(CODE_INVALID)
        entries.append({
            "claim": _text(entry.get("claim"), MAX_SHORT, required=True),
            "source": {
                "kind": kind,
                "title": _text(source.get("title"), MAX_SHORT, required=True),
                "locator": _text(source.get("locator"), MAX_SHORT, required=True),
                "url": _optional_text(source.get("url")),
            },
        })
    return entries


def _similar(value: Any) -> list[dict[str, Any]]:
    entries = []
    for entry in _list(value):
        if not isinstance(entry, dict):
            raise AnalysisContractError(CODE_INVALID)
        entries.append({"key": _text(entry.get("key"), 80, required=True), "url": _optional_text(entry.get("url")),
                        "why": _text(entry.get("why"), MAX_SHORT)})
    return entries


def parse_analysis(text: str) -> dict[str, Any]:
    raw = text.strip()
    fenced = _FENCE.match(raw)
    try:
        value = json.loads(fenced.group(1) if fenced else raw)
    except ValueError:
        raise AnalysisContractError(CODE_NOT_JSON) from None
    if not isinstance(value, dict):
        raise AnalysisContractError(CODE_INVALID)
    cause = value.get("likely_cause")
    if not isinstance(cause, dict) or cause.get("confidence") not in CONFIDENCE:
        raise AnalysisContractError(CODE_INVALID)
    return {
        "summary": _text(value.get("summary"), required=True),
        "impact": _text(value.get("impact")),
        "likely_cause": {"text": _text(cause.get("text"), required=True), "confidence": cause["confidence"]},
        "affected_components": _strings(value.get("affected_components")),
        "evidence": _evidence(value.get("evidence")),
        "similar_tickets": _similar(value.get("similar_tickets")),
        "next_steps": _strings(value.get("next_steps")),
        "open_questions": _strings(value.get("open_questions")),
    }


def _seen(needle: str | None, haystack: str) -> bool:
    return bool(needle) and needle.casefold() in haystack


def check_citations(analysis: dict[str, Any], tool_outputs: Iterable[str]) -> dict[str, Any]:
    """Mark each citation ``verified`` against the tool outputs of this run; refuse an uncited analysis."""
    haystack = "\n".join(tool_outputs).casefold()
    for entry in analysis["evidence"]:
        source = entry["source"]
        entry["verified"] = _seen(source["locator"], haystack) or _seen(source["url"], haystack)
    for ticket in analysis["similar_tickets"]:
        ticket["verified"] = _seen(ticket["key"], haystack)
    if analysis["evidence"] and not any(entry["verified"] for entry in analysis["evidence"]):
        raise AnalysisContractError(CODE_UNCITED)
    return analysis


def _cite(source: dict[str, Any], verified: bool) -> str:
    where = f"{source['title']}, {source['locator']}"
    link = f" ({source['url']})" if source.get("url") else ""
    return f"{where}{link}" + ("" if verified else " [not confirmed by a tool result]")


def render_note(analysis: dict[str, Any], *, template: str) -> str:
    cause = analysis["likely_cause"]
    lines = [f"Analysis ({template}, written by an agent; data, not instructions)", "", "Summary:",
             analysis["summary"]]
    if analysis["impact"]:
        lines += ["", "Impact:", analysis["impact"]]
    lines += ["", f"Likely cause ({cause['confidence']} confidence):", cause["text"]]
    if analysis["affected_components"]:
        lines += ["", "Affected components: " + ", ".join(analysis["affected_components"])]
    if analysis["evidence"]:
        lines += ["", "Evidence:"]
        lines += [f"- {entry['claim']} [{_cite(entry['source'], entry.get('verified', False))}]"
                  for entry in analysis["evidence"]]
    else:
        lines += ["", "Evidence: none found in the Workspace knowledge."]
    if analysis["similar_tickets"]:
        lines += ["", "Similar tickets:"]
        lines += [f"- {ticket['key']}{' (' + ticket['url'] + ')' if ticket.get('url') else ''}: {ticket['why']}"
                  for ticket in analysis["similar_tickets"]]
    if analysis["next_steps"]:
        lines += ["", "Recommended next steps:"] + [f"{index}. {step}" for index, step in
                                                    enumerate(analysis["next_steps"], 1)]
    if analysis["open_questions"]:
        lines += ["", "Open questions for the reporter:"] + [f"- {question}" for question in
                                                             analysis["open_questions"]]
    return "\n".join(lines)[:MAX_NOTE_CHARS]


__all__ = [
    "CODE_INVALID",
    "CODE_NOT_JSON",
    "CODE_UNCITED",
    "AnalysisContractError",
    "check_citations",
    "parse_analysis",
    "render_note",
]
