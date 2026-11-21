"""Confining a JQL query to allowed projects, so it can never break out.

Shared by the agent tools (``_jira_helpers_jql._inject_project_restriction``) and the Secure Work intake
(``services/secure_work/jira/jira_scope.restrict_jql``).

A scanner reads the JQL the way Jira does for this purpose: quoted strings (``"…"`` and ``'…'``, with
backslash escapes) are opaque, parentheses nest outside quotes, and ``ORDER BY`` counts only at the top
level outside quotes, so ``summary ~ "order by"`` is never split.

- :func:`jql_is_balanced` is False for an unterminated quote or a parenthesis that closes more than it
  opened (``project = OCX) OR (project = OPS``). Callers refuse such a query instead of sending it.
- A backslash outside a quoted string is refused too (``jql_invalid``): Jira's lexer
  reads ``\\`` as an escape inside *and* outside quotes, so ``\\"`` outside quotes would end a string
  the scanner believes open. The scanner skips the escaped character like Jira, and every caller refuses.
- :func:`confine_jql` returns ``project in (<keys>) AND (<body>) [ORDER BY …]``. The body is balanced by
  construction (defense in depth for a caller that did not refuse), so the user's text always stays
  inside the one group and the project clause always binds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ORDER_BY = re.compile(r"order\s+by\b", re.IGNORECASE)
_QUOTES = ('"', "'")


@dataclass(frozen=True, slots=True)
class JqlShape:
    deficit: int  # how many more ")" than "(" at the worst point
    depth: int  # the open "(" left at the end (after the deficit)
    open_quote: str | None  # an unterminated quote character
    order_by_at: int | None  # index of the first top-level ORDER BY outside quotes
    bare_backslash: bool = False  # a backslash outside a quoted string (refused, C-1b)

    @property
    def balanced(self) -> bool:
        return self.deficit == 0 and self.depth == 0 and self.open_quote is None

    @property
    def safe(self) -> bool:
        return self.balanced and not self.bare_backslash


class UnsafeJqlError(ValueError):
    """A JQL that could leave its group; callers refuse it before it is ever confined or sent."""


def scan_jql(text: str) -> JqlShape:
    depth = deficit = 0
    quote: str | None = None
    order_by_at: int | None = None
    bare_backslash = False
    index = 0
    while index < len(text):
        char = text[index]
        if quote is None and char == "\\":
            bare_backslash = True  # Jira escapes the next character here too
            index += 2
            continue
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in _QUOTES:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                deficit += 1
            else:
                depth -= 1
        elif (
            depth == 0
            and order_by_at is None
            and (index == 0 or not (text[index - 1].isalnum() or text[index - 1] == "_"))
            and _ORDER_BY.match(text, index)
        ):
            order_by_at = index
        index += 1
    return JqlShape(deficit=deficit, depth=depth, open_quote=quote, order_by_at=order_by_at,
                    bare_backslash=bare_backslash)


def jql_problem(jql: str) -> str | None:
    """``jql_invalid`` (a backslash outside quotes), ``jql_unbalanced``, or ``None`` for a safe JQL."""
    shape = scan_jql(str(jql or ""))
    if shape.bare_backslash:
        return "jql_invalid"
    return None if shape.balanced else "jql_unbalanced"


def jql_is_balanced(jql: str) -> bool:
    """Whether the JQL is safe to confine: quotes closed, parentheses balanced, no backslash outside quotes."""
    return jql_problem(jql) is None


def _balanced(body: str) -> str:
    shape = scan_jql(body)
    if shape.balanced:
        return body
    # Only reached for a caller that sent an unrefused, malformed query: close it inside the group.
    closed = "(" * shape.deficit + body + (shape.open_quote or "")
    return closed + ")" * scan_jql(closed).depth


def split_order_by(jql: str) -> tuple[str, str]:
    """``(body, "ORDER BY …")`` at the first top-level ORDER BY outside quotes; ``(jql, "")`` without one."""
    text = str(jql or "").strip()
    shape = scan_jql(text)
    if shape.order_by_at is None or not shape.balanced:
        return text, ""
    return text[: shape.order_by_at].strip(), text[shape.order_by_at :].strip()


def confine_jql(jql: str, project_clause: str) -> str:
    """``<project_clause> AND (<body>) <ORDER BY>``: the body can never escape the clause."""
    if scan_jql(str(jql or "")).bare_backslash:
        raise UnsafeJqlError("jql_invalid")  # never confined by guesswork: callers refuse it first
    body, order = split_order_by(jql)
    restricted = f"{project_clause} AND ({_balanced(body)})" if body else project_clause
    return f"{restricted} {order}".strip()


__all__ = ["JqlShape", "UnsafeJqlError", "confine_jql", "jql_is_balanced", "jql_problem", "scan_jql", "split_order_by"]
