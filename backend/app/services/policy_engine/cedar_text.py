"""Cedar source rendering: string literals, entity references, ``like`` patterns and one policy statement.

Every value the translator writes into Cedar text goes through :func:`literal`, so a Workspace id, an alias or a
command token can never break out of its string. ``fnmatch`` globs (the gateway ``path_denied`` rules) become
``like`` patterns: ``*`` is exact (fnmatch's ``*`` also matches ``/``, like Cedar's), ``?`` and ``[...]`` have no
Cedar equivalent and widen to ``*`` — reported as approximate so the translator can flag the rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\0": "\\0"}


def _escaped_char(char: str) -> str:
    if char in _ESCAPES:
        return _ESCAPES[char]
    if ord(char) < 0x20 or ord(char) == 0x7F:
        return f"\\u{{{ord(char):x}}}"
    return char


def literal(value: str) -> str:
    """A Cedar string literal for ``value``."""
    return '"' + "".join(_escaped_char(char) for char in str(value)) + '"'


def entity(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}::{literal(entity_id)}"


def action(name: str) -> str:
    return entity("Action", name)


def action_scope(names: Iterable[str]) -> str:
    listed = list(names)
    if len(listed) == 1:
        return f"action == {action(listed[0])}"
    return "action in [" + ", ".join(action(name) for name in listed) + "]"


def string_set(values: Iterable[str]) -> str:
    return "[" + ", ".join(literal(value) for value in values) + "]"


@dataclass(frozen=True, slots=True)
class LikePattern:
    text: str
    approximate: bool


def glob_to_like(glob: str) -> LikePattern:
    """The ``like`` pattern (with quotes) for an ``fnmatchcase`` glob; ``approximate`` when it had ``?``/``[...]``."""
    parts: list[str] = []
    approximate = False
    index, size = 0, len(glob)
    while index < size:
        char = glob[index]
        index += 1
        if char == "*":
            parts.append("*")
        elif char == "?":
            parts.append("*")
            approximate = True
        elif char == "[":
            end = index
            if end < size and glob[end] == "!":
                end += 1
            if end < size and glob[end] == "]":
                end += 1
            while end < size and glob[end] != "]":
                end += 1
            if end >= size:
                parts.append("[")  # fnmatch: an unclosed bracket is a literal
            else:
                parts.append("*")
                approximate = True
                index = end + 1
        else:
            parts.append(_escaped_char(char))
    return LikePattern('"' + "".join(parts) + '"', approximate)


@dataclass(frozen=True, slots=True)
class GeneratedPolicy:
    """One generated Cedar policy: its ``@id`` and its full source text."""

    policy_id: str
    text: str


def policy(
    policy_id: str,
    effect: str,
    *,
    actions: Iterable[str],
    principal: str = "principal",
    resource: str = "resource",
    when: Iterable[str] = (),
    unless: Iterable[str] = (),
    annotations: Iterable[tuple[str, str]] = (),
) -> GeneratedPolicy:
    """Render ``@id(...) effect(principal, action ..., resource) when {...} unless {...};``."""
    lines = [f"@id({literal(policy_id)})"]
    lines.extend(f"@{name}({literal(value)})" for name, value in annotations)
    lines.append(f"{effect} ({principal}, {action_scope(actions)}, {resource})")
    conditions = [condition for condition in when if condition]
    if conditions:
        lines.append("when { " + " && ".join(conditions) + " }")
    exceptions = [condition for condition in unless if condition]
    if exceptions:
        lines.append("unless { " + " && ".join(exceptions) + " }")
    return GeneratedPolicy(policy_id, "\n".join(lines) + ";")


def render(policies: Iterable[GeneratedPolicy]) -> str:
    return "\n\n".join(item.text for item in policies) + "\n"


__all__ = [
    "GeneratedPolicy",
    "LikePattern",
    "action",
    "action_scope",
    "entity",
    "glob_to_like",
    "literal",
    "policy",
    "render",
    "string_set",
]
