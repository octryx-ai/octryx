"""What the platform's tool-result check says about a finished tool, as PostToolUse output.

``POST /sessions/tool-executed`` answers with ``content`` when a content policy acts on the tool's output:
what was found (detector × count, never the data), whether it is masked or kept out of the model, the policy and
the decision. The launcher shows the user a one-line notice (``systemMessage``) and tells the model that the
values are masked placeholders (``additionalContext``). For an MCP tool the platform returns the masked output,
which replaces the original (``updatedMCPToolOutput``). Parts the platform could not finish checking (``kind:
withhold``) are withheld: an MCP tool gets the withheld output, and the model is told why (``additionalContext``).
A built-in tool's output stays as Claude Code has it (``kept_by_client``): the notice says what was found and that
the gateway checks a request carrying it (it refuses one a Workspace policy denies) — nothing is called masked,
withheld or kept out.

When the gateway routes a conversation to a governed model because of a content policy, the PostToolUse and Stop
answers carry ``content_route`` (categories, detector counts, policy, decision, target; never the data).
``route_notice_once`` turns it into a one-time ``systemMessage`` per conversation (``/clear`` starts a new one).
"""

from __future__ import annotations

import re
from typing import Any

from .state import LocalState, read_json, write_private_json

MODEL_NOTE = ("Octryx content policy: values in this tool output are masked before any model sees them; "
              "the bracketed, numbered placeholders are not real values. Do not try to recover them.")
WITHHELD_NOTE = ("Octryx content policy: parts of this tool output were too large or dense to check, so they are "
                 "withheld and never reach a model. Ask for a smaller part of the output instead.")
BLOCKED_NOTE = ("Octryx content policy: this tool output is kept out of the model because it contains "
                "data the Workspace policy does not allow. Use a governed tool that returns masked data instead.")
KEPT_NOTE = ("Octryx content policy: this tool output contains data a Workspace policy acts on; it is not changed "
             "here, and the gateway may refuse a request that carries it. Prefer a governed tool for such data.")


def _found(content: dict[str, Any]) -> str:
    found = content.get("found") if isinstance(content.get("found"), dict) else {}
    return ", ".join(f"{key} ×{value}" for key, value in found.items() if isinstance(value, int)) or "sensitive data"


def content_output(result: Any, tool_name: str) -> dict[str, Any] | None:
    """The PostToolUse output for the platform's answer, or ``None`` when no policy acted on the output."""
    content = result.get("content") if isinstance(result, dict) else None
    if not isinstance(content, dict) or not content:
        return None
    blocked = content.get("blocked") is True
    kept = content.get("kept_by_client") is True
    if content.get("kind") == "withhold" and not blocked and not kept:
        return _withheld_output(content, tool_name)
    policies = ", ".join(str(item) for item in content.get("policies") or [] if isinstance(item, str))
    decision = str(content.get("decision_id") or "")
    reference = " · ".join(part for part in (f"policy {policies}" if policies else "",
                                             f"decision {decision}" if decision else "") if part)
    if kept:
        message = (f"Octryx: {_found(content)} found; this output stays as it is and the gateway checks it"
                   + (f" ({reference})" if reference else ""))
        return {"systemMessage": message,
                "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": KEPT_NOTE}}
    verb = "kept out of the model" if blocked else "masked"
    message = f"Octryx: {_found(content)} {verb}" + (f" ({reference})" if reference else "")
    specific: dict[str, Any] = {"hookEventName": "PostToolUse",
                                "additionalContext": BLOCKED_NOTE if blocked else MODEL_NOTE}
    if tool_name.startswith("mcp__") and "updated_output" in content and not blocked:
        specific["updatedMCPToolOutput"] = content["updated_output"]
    return {"systemMessage": message, "hookSpecificOutput": specific}


def _withheld_output(content: dict[str, Any], tool_name: str) -> dict[str, Any]:
    """The platform withheld parts it could not finish checking: an MCP tool gets the withheld output; a built-in
    tool's output stays with Claude Code, and the gateway withholds or refuses it before any model reads it."""
    withheld = content.get("withheld") if type(content.get("withheld")) is int else 0
    specific: dict[str, Any] = {"hookEventName": "PostToolUse", "additionalContext": WITHHELD_NOTE}
    if tool_name.startswith("mcp__") and "updated_output" in content:
        specific["updatedMCPToolOutput"] = content["updated_output"]
    return {"systemMessage": f"Octryx: {withheld or 'some'} part(s) of this output too large to check, withheld",
            "hookSpecificOutput": specific}


ROUTE_NOTICE_FILE = "content_route_notice.json"
MAX_REMEMBERED = 50
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")
CATEGORY_WORDS = {"pii": "personal data", "secrets": "credentials", "health": "health data"}


def _name(value: object) -> str:
    return value if isinstance(value, str) and _NAME.match(value) and not value.isdigit() else ""


def route_message(route: dict[str, Any], *, seat: bool) -> str:
    """The terminal notice for a routed conversation (names and counts only)."""
    alias = _name(route.get("route_to")) or "the approved model"
    categories = [_name(item) for item in route.get("categories") or [] if _name(item)]
    words = " and ".join(dict.fromkeys(CATEGORY_WORDS.get(item, f"{item} data") for item in categories))
    counts = route.get("detectors") if isinstance(route.get("detectors"), dict) else {}
    found = ", ".join(f"{key} ×{value}" for key, value in counts.items() if _name(key) and type(value) is int)
    reason = f"it contained {words or 'sensitive data'}" + (f" ({found})" if found else "")
    reference = " · ".join(part for part in (f"Policy: {_name(route.get('policy_id'))}" if _name(route.get("policy_id"))
                                             else "", f"decision {_name(route.get('decision_id'))}"
                                             if _name(route.get("decision_id")) else "") if part)
    back = "your seat model" if seat else "your model"
    return (f"Octryx · This conversation now runs on {alias} (governed) because {reason}."
            + (f"\n{reference}" if reference else "")
            + f"\nMasked values are placeholders. Start a new conversation (/clear) to return to {back}.")


def route_notice_once(state: LocalState, session_key: str, body: Any, *, seat: bool) -> str:
    """The notice the first time a conversation is reported as routed; ``""`` afterwards and otherwise."""
    route = body.get("content_route") if isinstance(body, dict) else None
    conversation = _name(route.get("conversation")) if isinstance(route, dict) else ""
    if not conversation:
        return ""
    path = state.session_dir(session_key) / ROUTE_NOTICE_FILE
    shown = [item for item in read_json(path).get("shown") or [] if isinstance(item, str)]
    if conversation in shown:
        return ""
    write_private_json(path, {"shown": [*shown, conversation][-MAX_REMEMBERED:]})
    return route_message(route, seat=seat)


__all__ = ["BLOCKED_NOTE", "KEPT_NOTE", "MODEL_NOTE", "WITHHELD_NOTE", "content_output", "route_message",
           "route_notice_once"]
