"""One canonical ``issue_type`` for ``create_jira_ticket``, whatever spelling the model used."""

from __future__ import annotations

from typing import Any

ISSUE_TYPE_ALIASES = ("issue_type", "issuetype", "issueType", "issue_type_name", "issueTypeName")


def _alias_value(value: Any) -> str:
    if isinstance(value, dict):  # Jira's own shape: {"issuetype": {"name": "Epic"}}
        value = value.get("name") or value.get("id")
    return str(value).strip() if value not in (None, "") and not isinstance(value, (list, dict)) else ""


def normalize_issue_type_args(params: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
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
