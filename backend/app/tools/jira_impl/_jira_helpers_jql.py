"""Jira helper functions for JQL query validation and transformation."""

import re

from ._jira_jql_confine import confine_jql, split_order_by

_JQL_SIGNAL_PATTERN = re.compile(
    r"\b(updated|created|creator|resolved|status|project|labels?|assignee|reporter|issuetype|priority|summary|text)\b",
    re.IGNORECASE,
)
_JQL_OPERATOR_PATTERN = re.compile(r"(>=|<=|!=|=|~|\bin\b|\bnot in\b|\border by\b)", re.IGNORECASE)
_RELATIVE_DAY_PATTERN = re.compile(r"-(\d+)d\b", re.IGNORECASE)


def _looks_like_jql_query(query: str) -> bool:
    text = query.strip()
    if not text:
        return False
    return bool(_JQL_SIGNAL_PATTERN.search(text) and _JQL_OPERATOR_PATTERN.search(text))


def _normalize_jql_shorthand(jql: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        days = int(match.group(1))
        return f"-{days * 24}h"

    return _RELATIVE_DAY_PATTERN.sub(_replace, jql.strip())


def _split_order_by_clause(jql: str) -> tuple[str, str]:
    """The top-level ORDER BY outside quotes (a quoted "order by" is never split)."""
    return split_order_by(jql)


def _inject_project_restriction(jql: str, allowed_projects: list[str]) -> str:
    """``project in (...) AND (<jql>)``; the JQL can never break out of the group."""
    keys_quoted = ", ".join(f'"{k}"' for k in allowed_projects)
    return confine_jql(_normalize_jql_shorthand(jql), f"project in ({keys_quoted})")
