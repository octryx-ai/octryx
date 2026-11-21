"""One canonical ``issue_type`` for ``create_jira_ticket``, whatever spelling the model used.

Why: a model asked for an Epic with ``issuetype: "Epic"``
(Jira's own REST field name). The tool only read ``issue_type``, so the plan card said "Task: Hello Kitchen", its
"After" showed issue_type Task, and confirming would have created a Task instead of the requested Epic. So the aliases
Jira and weak models use are read too, the type the person asked for wins over the default, and two different types in
one call are refused instead of guessed.
"""

from __future__ import annotations

from typing import Any

ISSUE_TYPE_ALIASES = ("issue_type", "issuetype", "issueType", "issue_type_name", "issueTypeName")


def _alias_value(value: Any) -> str:
    if isinstance(value, dict):  # Jira's own shape: {"issuetype": {"name": "Epic"}}
        value = value.get("name") or value.get("id")
    return str(value).strip() if value not in (None, "") and not isinstance(value, (list, dict)) else ""


def normalize_issue_type_args(params: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    """``(params with only issue_type, error)``; ``error`` names conflicting types, the params are then unchanged."""
    params = dict(params or {})
    named = {alias: _alias_value(params.get(alias)) for alias in ISSUE_TYPE_ALIASES if alias in params}
    distinct: dict[str, str] = {}
    for value in named.values():
        if value:
            distinct.setdefault(value.lower(), value)
    if len(distinct) > 1:
        listed = ", ".join(f"{alias}={value!r}" for alias, value in named.items() if value)
        return params, (f"Conflicting issue types ({listed}). Send exactly one issue_type, the type the person asked "
                        "for.")
    for alias in named:
        params.pop(alias, None)
    if distinct:
        params["issue_type"] = next(iter(distinct.values()))
    return params, None


__all__ = ["ISSUE_TYPE_ALIASES", "normalize_issue_type_args"]
