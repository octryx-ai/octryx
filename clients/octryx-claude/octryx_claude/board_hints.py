"""Agent board hints in the hooks (S4): the handoff nudge and the takeover-decision guard.

- **Handoff nudge:** the verification answer lists ``handoff_nudges`` (``[{work_item_key, marker}]``) for the
  session's claims whose handoff is missing or behind. The Stop hook blocks with one line, "Update the handoff
  for BRD-x with work_item_handoff_write before stopping.", only for markers it has not nudged for yet; the
  markers are kept in the session state, so each change nudges once and the next stop goes through (no loop).
- **Decision guard:** a takeover is confirmed or declined by a person in the Octryx UI (root D1), never
  by the agent. PreToolUse denies any Bash command that calls a takeover decision endpoint.
"""

from __future__ import annotations

import re
from typing import Any

from .platform import PlatformResult

MAX_REMEMBERED_MARKERS = 50
_MARKER = re.compile(r"^[A-Za-z0-9:._\-]{1,120}$")
_KEY = re.compile(r"^[A-Za-z0-9._\-/#]{1,80}$")
_DECISION_ENDPOINT = re.compile(r"agent-board/takeovers/[^\s/'\"]+/(confirm|decline)", re.IGNORECASE)
DECISION_DENY_REASON = (
    "A takeover is confirmed or declined by a person in the Octryx UI (Agents → Claims and handoffs), "
    "never by an agent."
)


def handoff_nudges(result: PlatformResult) -> list[tuple[str, str, str]]:
    """``[(work item key, marker, kind)]`` from the verification answer; malformed entries are ignored.

    ``kind`` is ``update`` (this session's handoff is behind) or ``offer`` (judge-s4 F1: the item is offered to this
    agent; only its own ``work_item_takeover_request`` can take it over)."""
    raw = result.body.get("handoff_nudges") if result.outcome == "ok" else None
    found = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        key, marker = entry.get("work_item_key"), entry.get("marker")
        kind = "offer" if entry.get("kind") == "offer" else "update"
        if isinstance(key, str) and isinstance(marker, str) and _KEY.match(key) and _MARKER.match(marker):
            found.append((key, marker, kind))
    return found


def nudge_line(keys: list[str]) -> str:
    return f"Update the handoff for {', '.join(keys)} with work_item_handoff_write before stopping."


def offer_line(keys: list[str]) -> str:
    return (f"{', '.join(keys)} is offered to you for a takeover: if you can continue it, request it with "
            "work_item_takeover_request; otherwise ignore this.")


def with_handoff_nudge(
    output: dict[str, Any] | None, result: PlatformResult, *, nudged: list[str]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Block once per new marker; returns ``(output, remembered markers)``. An existing block gets the line."""
    fresh = [(key, marker, kind) for key, marker, kind in handoff_nudges(result) if marker not in nudged]
    if not fresh:
        return output, nudged
    remembered = (nudged + [marker for _, marker, _ in fresh])[-MAX_REMEMBERED_MARKERS:]
    updates = sorted({key for key, _, kind in fresh if kind == "update"})
    offers = sorted({key for key, _, kind in fresh if kind == "offer"})
    line = "\n".join([*([nudge_line(updates)] if updates else []), *([offer_line(offers)] if offers else [])])
    if output and output.get("decision") == "block":
        return {**output, "reason": f"{output['reason']}\n{line}"}, remembered
    blocked: dict[str, Any] = {"decision": "block", "reason": line}
    if output and output.get("systemMessage"):
        blocked["systemMessage"] = output["systemMessage"]
    return blocked, remembered


def calls_takeover_decision(tool_name: object, tool_input: object) -> bool:
    if tool_name != "Bash" or not isinstance(tool_input, dict):
        return False
    command = tool_input.get("command")
    return isinstance(command, str) and bool(_DECISION_ENDPOINT.search(command))


__all__ = [
    "DECISION_DENY_REASON",
    "calls_takeover_decision",
    "handoff_nudges",
    "nudge_line",
    "with_handoff_nudge",
]
