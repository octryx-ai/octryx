"""One policy set text as its single statements."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .engine import cedar_module, text_digest


@dataclass(frozen=True, slots=True)
class SplitText:
    statements: tuple[str, ...]
    trailer: str = ""


def split_statements(text: str) -> SplitText:
    statements: list[str] = []
    start = 0
    index, size = 0, len(text)
    quoted = escaped = comment = False
    while index < size:
        char = text[index]
        if comment:
            comment = char != "\n"
        elif quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "/" and text.startswith("//", index):
            comment = True
        elif char == ";":
            statements.append(text[start:index + 1].strip())
            start = index + 1
        index += 1
    return SplitText(tuple(item for item in statements if item), text[start:].strip())


@dataclass(frozen=True, slots=True)
class References:
    entities: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    connections: tuple[str, ...] = ()
    uses_principal: bool = False

    def of(self, entity_type: str) -> tuple[str, ...]:
        return tuple(self.entities.get(entity_type, ()))

    def to_dict(self) -> dict[str, Any]:
        return {"entities": {key: list(value) for key, value in sorted(self.entities.items())},
                "connections": list(self.connections)}


@dataclass(frozen=True, slots=True)
class Statement:
    policy_id: str
    text: str
    digest: str
    effect: str
    actions: tuple[str, ...]
    annotations: Mapping[str, str]
    est: Mapping[str, Any]
    references: References

    @property
    def has_conditions(self) -> bool:
        return bool(self.est.get("conditions"))


def _walk(node: Any) -> Iterable[Any]:
    yield node
    if isinstance(node, Mapping):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _connections_attr(node: Any) -> bool:
    access = node.get(".") if isinstance(node, Mapping) else None
    return isinstance(access, Mapping) and access.get("attr") == "connections" and access.get("left") == {
        "Var": "context"}


def _strings(node: Any) -> list[str]:
    items = node.get("Set") if isinstance(node, Mapping) else None
    if items is None and isinstance(node, Mapping) and isinstance(node.get("Value"), str):
        return [node["Value"]]
    return [item["Value"] for item in items or () if isinstance(item, Mapping) and isinstance(item.get("Value"), str)]


def references_of(est: Mapping[str, Any]) -> References:
    entities: dict[str, list[str]] = {}
    connections: list[str] = []
    for node in _walk(est):
        if not isinstance(node, Mapping):
            continue
        ref = node.get("__entity") if "__entity" in node else (node if {"type", "id"} <= set(node) else None)
        if isinstance(ref, Mapping) and isinstance(ref.get("type"), str) and ref.get("type") != "Action":
            entities.setdefault(ref["type"], []).append(str(ref.get("id")))
        for operator in ("contains", "containsAny", "containsAll"):
            call = node.get(operator)
            if isinstance(call, Mapping) and _connections_attr(call.get("left")):
                connections.extend(_strings(call.get("right")))
    principal = est.get("principal") or {}
    uses_principal = principal.get("op") not in (None, "All") or '{"Var": "principal"}' in json.dumps(
        est.get("conditions") or [])
    return References(
        {key: tuple(dict.fromkeys(values)) for key, values in entities.items()},
        tuple(dict.fromkeys(connections)),
        uses_principal,
    )


def _actions(scope: Mapping[str, Any], every: Iterable[str]) -> tuple[str, ...]:
    if scope.get("op") == "==":
        return (str(scope["entity"]["id"]),)
    if scope.get("op") == "in" and "entities" in scope:
        return tuple(str(item["id"]) for item in scope["entities"])
    return tuple(every)


def _positional(name: str) -> int:
    digits = "".join(char for char in name if char.isdigit())
    return int(digits) if digits else 0


def index_statements(text: str, *, every_action: Iterable[str] = ()) -> list[Statement]:
    split = split_statements(text)
    est = json.loads(cedar_module().policies_to_json_str(text)) if split.statements else {}
    bodies = [body for _, body in sorted((est.get("staticPolicies") or {}).items(),
                                         key=lambda item: _positional(item[0]))]
    if len(bodies) != len(split.statements):
        raise ValueError("policy_text_statements_unaligned")
    every = tuple(every_action)
    indexed: list[Statement] = []
    for statement, body in zip(split.statements, bodies, strict=True):
        annotations = {str(key): str(value) for key, value in (body.get("annotations") or {}).items()}
        indexed.append(Statement(
            policy_id=annotations.get("id", ""),
            text=statement,
            digest=text_digest(statement),
            effect=str(body.get("effect") or ""),
            actions=_actions(body.get("action") or {}, every),
            annotations=annotations,
            est=body,
            references=references_of(body),
        ))
    return indexed


def join_statements(statements: Iterable[tuple[str, str]], trailer: str = "") -> str:
    ordered = [text.strip() for _, text in sorted(statements, key=lambda item: item[0])]
    parts = [*ordered, trailer.strip()] if trailer.strip() else ordered
    return "\n\n".join(parts) + "\n" if parts else ""


__all__ = [
    "References",
    "SplitText",
    "Statement",
    "index_statements",
    "join_statements",
    "references_of",
    "split_statements",
]
