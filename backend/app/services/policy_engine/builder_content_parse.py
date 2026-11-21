"""Content policies read back from Cedar (EST → values); the caller re-renders and compares the text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .builder_content import Content, Outcome
from .builder_est import Found, RefusedError, chain, op, path, strings, value


def _is_detected(node: Any) -> bool:
    try:
        operator, body = op(node)
        return operator == "containsAny" and path(body["left"]) == ("context", "content", "detected")
    except (RefusedError, KeyError, TypeError):
        return False


def _sticky_categories(node: Any) -> tuple[str, ...]:
    operator, body = op(node)
    if operator != "&&":
        raise RefusedError
    left_op, left = op(body["left"])
    right_op, right = op(body["right"])
    if left_op != "is" or left.get("entity_type") != "AgentSession" or path(left["left"]) != ("principal",) \
            or right_op != "containsAny" or path(right["left"]) != ("principal", "sensitive"):
        raise RefusedError
    return strings(right["right"])


def _is_incomplete(node: Any) -> bool:
    try:
        operator, body = op(node)
        if operator != "&&" or path(body["left"]) != ("context", "content", "scanned"):
            return False
        inner_op, inner = op(body["right"])
        return inner_op == "!" and path(inner["arg"]) == ("context", "content", "complete")
    except (RefusedError, KeyError, TypeError):
        return False


def read_content_when(node: Any, found: Found) -> bool:
    """Consume a route condition or the content group; ``False`` when ``node`` is neither."""
    operator, body = op(node)
    if operator == "==" and isinstance(body, Mapping) and _path_or_none(body.get("left")) == ("context", "route"):
        found.put("route", value(body["right"]))
        return True
    parts = chain(node, "||")
    if not _is_detected(parts[0]):
        return False
    found.put("detectors", strings(op(parts[0])[1]["right"]))
    for part in parts[1:]:
        if _is_incomplete(part):
            found.put("incomplete", True)
        else:
            found.put("sticky", True)
            found.put("categories", _sticky_categories(part))
    return True


def _path_or_none(node: Any) -> tuple[str, ...] | None:
    try:
        return path(node)
    except RefusedError:
        return None


def read_content_unless(node: Any, found: Found) -> bool:
    """Consume the route exception or the approved-model exception; ``False`` when ``node`` is neither."""
    operator, body = op(node)
    if operator == "containsAll" and _path_or_none(body.get("left")) == ("resource", "approved_for"):
        found.put("approved_except", True)
        found.put("categories", strings(body["right"]))
        return True
    if operator != "&&":
        return False
    parts = chain(node, "&&")
    first_op, first = op(parts[0])
    if first_op != "==" or _path_or_none(first.get("left")) != ("context", "route") or len(parts) not in (2, 3):
        return False
    if value(first["right"]) != "governed":
        raise RefusedError
    approved_op, approved = op(parts[1])
    if approved_op != "containsAll" or path(approved["left"]) != ("resource", "approved_for"):
        raise RefusedError
    found.put("categories", strings(approved["right"]))
    if len(parts) == 3:
        negated_op, negated = op(parts[2])
        if negated_op != "!" or not _is_detected(negated["arg"]):
            raise RefusedError
    return True


def content_of(values: Mapping[str, Any], annotations: Mapping[str, str]) -> tuple[Content, Outcome]:
    """The content and outcome sections read back; the re-render decides whether they are exactly the text."""
    content = Content(detectors=values.get("detectors", ()), sticky=values.get("sticky", False),
                      incomplete=values.get("incomplete", False), categories=values.get("categories", ()))
    outcome = Outcome(kind=annotations.get("obligation", "block"), reroute_to=annotations.get("reroute_to", ""),
                      mask_style=annotations.get("mask_style", ""),
                      approved_except=values.get("approved_except", False))
    return content, outcome


__all__ = ["content_of", "read_content_unless", "read_content_when"]
