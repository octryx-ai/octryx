"""Confining a JQL query to allowed projects, so it can never break out."""

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
    pass


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
    shape = scan_jql(str(jql or ""))
    if shape.bare_backslash:
        return "jql_invalid"
    return None if shape.balanced else "jql_unbalanced"


def jql_is_balanced(jql: str) -> bool:
    return jql_problem(jql) is None


def _balanced(body: str) -> str:
    shape = scan_jql(body)
    if shape.balanced:
        return body
    # Only reached for a caller that sent an unrefused, malformed query: close it inside the group.
    closed = "(" * shape.deficit + body + (shape.open_quote or "")
    return closed + ")" * scan_jql(closed).depth


def split_order_by(jql: str) -> tuple[str, str]:
    text = str(jql or "").strip()
    shape = scan_jql(text)
    if shape.order_by_at is None or not shape.balanced:
        return text, ""
    return text[: shape.order_by_at].strip(), text[shape.order_by_at :].strip()


def confine_jql(jql: str, project_clause: str) -> str:
    if scan_jql(str(jql or "")).bare_backslash:
        raise UnsafeJqlError("jql_invalid")  # never confined by guesswork: callers refuse it first
    body, order = split_order_by(jql)
    restricted = f"{project_clause} AND ({_balanced(body)})" if body else project_clause
    return f"{restricted} {order}".strip()


__all__ = ["JqlShape", "UnsafeJqlError", "confine_jql", "jql_is_balanced", "jql_problem", "scan_jql", "split_order_by"]
