"""What a kind's configured action actually does at each enforcement point, from handling_points.POINTS."""

from __future__ import annotations

from collections.abc import Mapping

from .handling import (
    ACTION_MASK,
    ACTION_NONE,
    ACTION_REFUSE,
    ACTION_REROUTE,
    ACTIONS,
    COMMAND_KINDS,
    REASON_DEFERRED_TO_MODEL,
    REASON_PLATFORM_ONLY,
    REASON_REROUTE_MASKED,
    REASON_ROUTE_UNAVAILABLE,
    REROUTING,
    SHIPPED_DEFAULTS,
    SURFACE_COMMANDS,
)
from .handling_points import POINTS, REROUTE_AS_MASK, REROUTE_UNAVAILABLE, EnforcementPoint


def point_action(point: EnforcementPoint, action: str, kind: str = "") -> tuple[str, str | None]:
    if (kind and kind not in point.kinds) or (action in ACTIONS and action not in point.supported):
        default = SHIPPED_DEFAULTS[point.surface].get(kind, ACTION_NONE) if kind in point.kinds else ACTION_NONE
        return default, REASON_PLATFORM_ONLY
    if action in point.deferred:
        return ACTION_NONE, REASON_DEFERRED_TO_MODEL
    if action in point.applied_as:
        return point.applied_as[action]
    if action in REROUTING and point.reroute == REROUTE_AS_MASK:
        return ACTION_MASK, REASON_REROUTE_MASKED
    if action in REROUTING and point.reroute == REROUTE_UNAVAILABLE:
        return ACTION_REFUSE, REASON_ROUTE_UNAVAILABLE
    return action, None


def _points(kind: str, reason: str) -> list[dict[str, str]]:
    return [{"surface": point.id, "label": point.label} for point in POINTS
            if kind in point.kinds and point_action(point, ACTION_REROUTE, kind)[1] == reason]


def reroute_unavailable(kind: str) -> list[dict[str, str]]:
    return _points(kind, REASON_ROUTE_UNAVAILABLE)


def reroute_masked_at(kind: str) -> list[dict[str, str]]:
    return _points(kind, REASON_REROUTE_MASKED)


def _conditions(point: EnforcementPoint, kind: str, action: str, applied: str) -> list[dict[str, str]]:
    return [{"where": rule.where, "label": rule.label, "action": rule.action, "reason": rule.reason}
            for rule in point.conditions if kind in rule.kinds and action in rule.when and applied != rule.action]


def fixed_outcomes() -> list[dict[str, object]]:
    return [{"surface": point.id, "label": point.label,
             "rules": [{"rule": item.rule, "action": item.action, "label": item.label} for item in point.fixed]}
            for point in POINTS]


def _configured(kind: str, surface: str, settings: Mapping[str, str]) -> str:
    if kind in settings and (surface != SURFACE_COMMANDS or kind in COMMAND_KINDS):
        return settings[kind]
    return SHIPPED_DEFAULTS[surface].get(kind, ACTION_NONE)


def surface_actions(kind: str, settings: Mapping[str, str]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for point in POINTS:
        if kind not in point.kinds and point.surface == SURFACE_COMMANDS:
            continue
        configured = _configured(kind, point.surface, settings)
        action, reason = point_action(point, configured, kind)
        found.append({"surface": point.id, "label": point.label, "configured_action": configured,
                      "action": action, "reason": reason,
                      "conditions": _conditions(point, kind, configured, action)})
    return found


__all__ = ["fixed_outcomes", "point_action", "reroute_masked_at", "reroute_unavailable", "surface_actions"]
