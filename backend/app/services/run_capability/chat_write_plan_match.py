"""A plan-admitted chat write runs with the arguments the person confirmed, never with fewer or other ones.

Example: the write plan the person confirmed says ``create_jira_ticket {issue_type: Story, description: ...,
project_key: PROJ, summary: ...}``. A weak model then calls ``create_jira_ticket {project_key: PROJ, summary: ...}``;
a gate that checks only tool and project admits it, Jira applies the default type and creates a **Task**, while the
answer says "Story". The plan named the target, but nothing checked that the executed call carried the plan's own
fields.

So before a covered write runs, it is matched to the confirmed write it performs:

- a field the confirmed write names and the call leaves out is filled from the plan (in the example: issue_type
  Story and the description come back), and the result says so (``write_plan.filled_from_plan``);
- a field that decides *what* is written (issue type, priority, labels, assignee, ...) must equal the plan's: a call
  that sets one differently, or sets one the plan left out, is refused with ``write_plan_mismatch`` and the confirmed
  arguments to call instead (``next_calls``);
- free text (summary, description, comment, ...) and targets stay within the confirmed scope without asking again,
  so a comment on another issue of the confirmed project still runs;
- when several confirmed writes fit and they would fill different values, the call is refused with all of them rather
  than guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

CODE_PLAN_MISMATCH = "write_plan_mismatch"
# Free text: the plan's wording is a draft, the call may phrase it (the scope rule governs where it lands).
FREE_TEXT_FIELDS = frozenset({
    "summary", "description", "comment", "body", "content", "text", "title", "note", "message", "subject",
    "commit_message", "pr_description", "reason", "why",
})
# How a call is routed, not what it writes.
ROUTING_FIELDS = frozenset({"connection", "connection_id", "connection_name"})


@dataclass
class PlanMatch:
    """The arguments to execute, what the plan filled in, or the refusal when the call does not match the plan."""

    fields: dict[str, Any]
    filled: dict[str, Any] = field(default_factory=dict)
    refusal: dict[str, Any] | None = None


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def canonical_fields(tool_name: str, fields: dict[str, Any] | None) -> dict[str, Any]:
    """The fields in the one spelling the tool executes (``issuetype`` -> ``issue_type``), empty values dropped."""
    fields = {key: value for key, value in dict(fields or {}).items() if _present(value)}
    if tool_name == "create_jira_ticket":
        from ...tools.jira_impl._jira_issue_type_args import normalize_issue_type_args

        normalized, conflict = normalize_issue_type_args(fields)
        if not conflict:
            return normalized
    return fields


def _comparable(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, (list, tuple, set)):
        return json.dumps(sorted(_comparable(item) for item in value))
    return json.dumps(value, sort_keys=True, default=str).casefold()


def _decides_what(key: str) -> bool:
    from .chat_write_plan import TARGET_PARAMS

    return key not in FREE_TEXT_FIELDS and key not in TARGET_PARAMS and key not in ROUTING_FIELDS


def mismatches(planned: dict[str, Any], call: dict[str, Any]) -> list[str]:
    """The fields deciding what is written that the call sets differently from the plan (or that the plan omits)."""
    found = []
    for key, value in call.items():
        if not _decides_what(key):
            continue
        if key not in planned:
            found.append(f"{key}: not in the plan, call {value!r}")
        elif _comparable(planned[key]) != _comparable(value):
            found.append(f"{key}: plan {planned[key]!r}, call {value!r}")
    return found


def _agreement(planned: dict[str, Any], call: dict[str, Any]) -> int:
    return sum(1 for key, value in call.items() if key in planned and _comparable(planned[key]) == _comparable(value))


def _refusal(tool_name: str, candidates: list[dict[str, Any]], reasons: list[str], plan_id: Any,
             why: str) -> dict[str, Any]:
    return {"error": (f"This {tool_name} call does not match the confirmed write plan ({why}). Call it with the "
                      "confirmed arguments in next_calls; for a different write, amend the plan with "
                      "propose_write_plan."),
            "code": CODE_PLAN_MISMATCH, "next_tool": tool_name, "mismatch": reasons, "plan_id": plan_id,
            "next_calls": [{"tool": tool_name, "arguments": planned} for planned in candidates],
            "blocked_by": "tool_approval_gate", "tool_name": tool_name}


def match_plan_write(plan: dict[str, Any], tool_name: str, params: dict[str, Any] | None) -> PlanMatch:
    """Match a covered call to the confirmed write it performs; fill what it left out or refuse a mismatch."""
    name = str(tool_name or "").strip()
    call = canonical_fields(name, params)
    planned_writes = [canonical_fields(name, write.get("fields")) for write in plan.get("writes") or []
                      if write.get("tool") == name]
    if not planned_writes:
        return PlanMatch(fields=call)
    fitting = [planned for planned in planned_writes if not mismatches(planned, call)]
    if not fitting:
        reasons = sorted({reason for planned in planned_writes for reason in mismatches(planned, call)})
        return PlanMatch(fields=call, refusal=_refusal(name, planned_writes, reasons, plan.get("plan_id"),
                                                       "; ".join(reasons)))
    best = max(_agreement(planned, call) for planned in fitting)
    closest = [planned for planned in fitting if _agreement(planned, call) == best]
    fills = [{key: value for key, value in planned.items() if key not in call} for planned in closest]
    if any(_comparable(fill) != _comparable(fills[0]) for fill in fills[1:]):
        return PlanMatch(fields=call, refusal=_refusal(name, closest, [], plan.get("plan_id"),
                                                       "it fits several confirmed writes; name which one"))
    return PlanMatch(fields={**call, **fills[0]}, filled=fills[0])


__all__ = ["CODE_PLAN_MISMATCH", "FREE_TEXT_FIELDS", "PlanMatch", "canonical_fields", "match_plan_write",
           "mismatches"]
