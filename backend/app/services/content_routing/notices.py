"""The user-facing content notices of a chat turn: closed, bounded, never the data.

A notice says what a content policy did with one model request or one tool result: the obligation kind, the
reason code, what was found (detector × count), how many values were masked, the deciding policies, the decision
record and the model change. Producers put the raw mapping in two structured places:

- the model-call notice (``content_security.model_call``: the shipped policies and ``chat.apply_chat_content``
  on success, the refusal's ``content_notice`` on failure)
  rides on the engine's runtime attempt as :data:`ATTEMPT_KEY`, so it is persisted in the trace's
  ``raw_output.runtime_attempts``;
- a checked tool result carries ``content_policy`` (``tools/result_content``), so the stored tool call keeps it.

:func:`turn_content_obligations` reads both back for ``turn_execution_summary.v1`` (``content_obligations``).
Every value is re-validated here: a closed enum, a bounded count, or a token that starts with a letter (detector,
policy, alias and tool names) or a decision id that is not all digits. Free text and anything shaped like a long
number never pass, so the summary cannot echo content even if a producer were wrong.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

ATTEMPT_KEY = "content_obligation"
TOOL_RESULT_KEY = "content_policy"
SOURCE_MODEL = "model"
SOURCE_TOOL_RESULT = "tool_result"
KINDS = frozenset({"mask", "reroute", "mask_reroute", "block"})
REASON_APPLIED = "content_obligation_applied"
REASONS = frozenset({
    REASON_APPLIED,
    "content_policy_denied",
    "content_policy_unavailable",
    "content_route_unavailable",
    "content_obligation_insufficient",
    "content_obligation_conflict",
})
MAX_NOTICES = 10
MAX_POLICIES = 10
MAX_FOUND = 20
_MAX_COUNT = 10**9
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/@+-]{0,127}$")
_DECISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$")


def name_token(value: Any) -> str | None:
    """A detector, category, policy, alias or tool name (starts with a letter), else ``None``."""
    return value if isinstance(value, str) and _TOKEN.match(value) else None


def decision_token(value: Any) -> str | None:
    """A decision record id (never all digits, so never shaped like an account number), else ``None``."""
    ok = isinstance(value, str) and _DECISION.match(value) and not value.isdigit()
    return value if ok else None


def _count(value: Any) -> int:
    return value if type(value) is int and 0 <= value <= _MAX_COUNT else 0


def closed_notice(raw: Any, *, source: str, tool: Any = None) -> dict[str, Any] | None:
    """The validated notice, or ``None`` when ``raw`` is not a notice (unknown kind or reason)."""
    if not isinstance(raw, Mapping) or raw.get("kind") not in KINDS:
        return None
    reason = raw.get("reason") or REASON_APPLIED
    if reason not in REASONS:
        return None
    found_raw = raw.get("found") if isinstance(raw.get("found"), Mapping) else {}
    found = {name: _count(count) for name, count in list(found_raw.items())[:MAX_FOUND]
             if name_token(name) and _count(count)}
    policies = [name for name in list(raw.get("policies") or [])[:MAX_POLICIES] if name_token(name)]
    return {
        "source": SOURCE_TOOL_RESULT if source == SOURCE_TOOL_RESULT else SOURCE_MODEL,
        "kind": raw["kind"],
        "reason": reason,
        "applied": reason == REASON_APPLIED,
        "found": found,
        "masked": _count(raw.get("masked")),
        "policies": policies,
        "decision_id": decision_token(raw.get("decision_id")),
        "model_from": name_token(raw.get("model_from")),
        "model_to": name_token(raw.get("model_to")),
        "tool": name_token(tool if tool is not None else raw.get("tool")),
    }


def attach_to_attempt(attempt: dict[str, Any], carrier: Any) -> None:
    """Copy a provider response's ``content_obligation`` or an error's ``content_notice`` onto its attempt."""
    raw = carrier.get(ATTEMPT_KEY) if isinstance(carrier, Mapping) else getattr(carrier, "content_notice", None)
    if isinstance(raw, Mapping) and raw:
        attempt[ATTEMPT_KEY] = dict(raw)


def _shown(notice: dict[str, Any]) -> bool:
    # A sticky route without new findings repeats the conversation's earlier notice; the turn shows nothing new.
    return not notice["applied"] or bool(notice["found"]) or bool(notice["masked"])


def _key(notice: dict[str, Any]) -> tuple:
    return (notice["source"], notice["kind"], notice["reason"], notice["tool"], notice["model_to"],
            tuple(sorted(notice["found"].items())))


def turn_content_obligations(raw_outputs: Iterable[Any], tool_results: Iterable[tuple[Any, Any]]
                             ) -> list[dict[str, Any]]:
    """The turn's notices: model requests (from the traces' runtime attempts) then tool results, deduplicated.

    ``tool_results`` are ``(tool_name, stored result)`` pairs; only the result's ``content_policy`` is read.
    """
    found: list[dict[str, Any]] = []
    for raw_output in raw_outputs:
        attempts = raw_output.get("runtime_attempts") if isinstance(raw_output, Mapping) else None
        for attempt in attempts if isinstance(attempts, list) else []:
            if isinstance(attempt, Mapping):
                found.append(closed_notice(attempt.get(ATTEMPT_KEY), source=SOURCE_MODEL))
    for tool_name, result in tool_results:
        if isinstance(result, Mapping):
            found.append(closed_notice(result.get(TOOL_RESULT_KEY), source=SOURCE_TOOL_RESULT, tool=tool_name))
    seen: set[tuple] = set()
    notices = []
    for notice in found:
        if notice is None or not _shown(notice) or _key(notice) in seen:
            continue
        seen.add(_key(notice))
        notices.append(notice)
    return notices[:MAX_NOTICES]


__all__ = [
    "ATTEMPT_KEY",
    "KINDS",
    "REASONS",
    "SOURCE_MODEL",
    "SOURCE_TOOL_RESULT",
    "TOOL_RESULT_KEY",
    "attach_to_attempt",
    "closed_notice",
    "decision_token",
    "name_token",
    "turn_content_obligations",
]
