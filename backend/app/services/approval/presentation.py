"""Approval texts in plain words: one formatter for every place an approval card is built or served.

Without it the cards read "Execute tool run_cli_command", "rule:
require_for_tools", "risk: write" - the gate's machine names. The person deciding on the phone needs to know what
runs where and why they are asked. This module turns the machine fields into English sentences (the UI is English;
the codes stay next to them for anything that wants to translate or branch):

* at build time (``tool_approval_gate.enforce_tool_approval``, the chat and write-plan previews) the stored preview
  gets a readable ``title``, ``subtitle`` (why the person is asked) and readable ``details``, plus ``rule``/``risk``
  as codes, while ``toolName``/``approvalSubject`` stay unchanged;
* at serve time (the chat card, ``GET /api/v1/approvals/{id}``, ``/decidable``, the attention queue)
  :func:`approval_texts` reads the stored preview and returns the same readable fields (a preview without a title,
  such as a write plan's single write, gets one from its tool);
* for Observability → Decisions (``decisions.timeline``) :func:`decision_what` and :func:`decision_rule_text` word
  a decision record's subject and rule codes, and a write plan's single writes are titled by :func:`readable_plan`
  whenever a preview is served.

Texts only name tools, systems and rules, never argument values; the values a card shows are the preview's own
fields, stored masked (``change_preview.upsert_change_preview``, ``secret_masking``). Sentences avoid ": " because the
connector and REST cards read "key: value" detail lines as fields.
"""

from __future__ import annotations

from typing import Any

from .tool_texts import _APPROVAL_ACTION, UNKNOWN_SYSTEM, readable_title, rule_text, system_label, tool_title


def _plan_line(line: str, number: int, tool: str, title: str) -> str:
    """``write 2: create_jira_ticket via Jira`` -> the title in words."""
    named = f"write {number}: {tool}"
    rest = line[len(named):]
    if line.startswith(named) and (not rest or rest.startswith(" via ")):
        return f"write {number}: {title}{rest}"
    return line


def readable_plan(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """A write plan preview whose single writes are titled in words, also on its flat lines.

    A readable plan title alone is not enough: its writes would still read "create_jira_ticket". The entry's ``tool``
    keeps the name; any other preview comes back unchanged."""
    if not isinstance(payload, dict) or payload.get("kind") != "write_plan":
        return payload
    if not isinstance(payload.get("writes"), list):
        return payload
    writes = [{**write, "title": readable_title(write.get("title"), write.get("tool"))} if isinstance(write, dict)
              else write for write in payload["writes"]]
    details = [str(line) for line in payload.get("details") or []]
    for position, write in enumerate(writes):
        if isinstance(write, dict) and write.get("tool"):
            number = int(write.get("index", position)) + 1
            details = [_plan_line(line, number, str(write["tool"]), write["title"]) for line in details]
    return {**payload, "writes": writes, "details": details}


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).strip(" .;").casefold()


def _without_sentence(line: str, sentence: str) -> str:
    """``line`` without ``sentence`` (the subtitle): "" when that is all it says, else the rest of the line.

    The details would otherwise repeat the subtitle ("This tool needs approval in this Workspace") as their first
    line."""
    if not sentence or _norm(line) == _norm(sentence):
        return "" if sentence else line
    position = line.casefold().find(sentence.casefold())
    if position < 0:
        return line
    rest = f"{line[:position].rstrip(' .;')}. {line[position + len(sentence):].lstrip(' .;')}".strip(" .;")
    return rest if _norm(rest) else ""


def plan_title(count: int, *, amendment: bool) -> str:
    noun = "write" if count == 1 else "writes"
    return f"{'Change to a write plan' if amendment else 'Write plan'} with {count} {noun}"


def approval_texts(payload: dict[str, Any] | None, action: str = "") -> dict[str, Any]:
    """``{title, subtitle, details}`` in words for a stored preview or, without one, the action.

    Idempotent on a preview this module wrote."""
    preview = readable_plan(payload) if isinstance(payload, dict) else {}
    details = [str(line) for line in preview.get("details") or [] if str(line or "").strip()]
    tool = str(preview.get("toolName") or "")
    rule = str(preview.get("rule") or "")
    risk = str(preview.get("risk") or "")
    system = system_label(tool) if tool else UNKNOWN_SYSTEM
    title = str(preview.get("title") or "")
    if preview.get("kind") == "write_plan" and isinstance(preview.get("writes"), list):
        title = plan_title(len(preview["writes"]), amendment=bool(preview.get("amends")))
    if not title:
        from_action = _APPROVAL_ACTION.match(str(action or ""))
        title = tool_title(tool) if tool else (tool_title(from_action.group("name")) if from_action
                                               else str(action or "") or "Approval")
    subtitle = str(preview.get("subtitle") or "") or rule_text(rule, risk=risk, system=system)
    readable = [_without_sentence(line, subtitle) for line in details]
    return {"title": title, "subtitle": subtitle, "details": [line for line in readable if line]}


__all__ = [
    "approval_texts",
    "plan_title",
    "readable_plan",
]
