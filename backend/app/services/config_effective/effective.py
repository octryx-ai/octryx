"""``effective(object, workspace)``: is an object available in a Workspace, and what applies there.

One pure function for every configuration object (connection now; model, workflow, agent, skill, knowledge
package and rule later): the caller hands in the object's availability (:class:`Subject`), its base values per
use and the Workspace's stored deviation; nothing here reads or writes the database.

- **available**: ``available_in == "all"``, or the Workspace is one of the object's Workspaces, or it owns it.
- **effective**: the base values with the deviation applied field by field through the object's rules
  (:data:`FieldRules`, ``narrowing.py``); a stored deviation that is no longer narrower is clamped to the base.
- **deviation**: the stored deviation (``None`` when there is none).

:func:`check_deviation` validates a deviation before it is stored: every field must have a rule and be narrower,
else :class:`DeviationNotNarrowerError` with the field path (``422 deviation_not_narrower``).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .narrowing import DeviationNotNarrowerError, narrow_schedule

AVAILABLE_ALL = "all"
AVAILABLE_SELECTED = "selected"
SCHEDULE_FIELD = "schedule"
SCHEDULE_COMPANION = "schedule_cron"

# ``{use: {field: rule}}``; a rule is ``(base value, deviation value, field path, *, strict) -> value``.
Rule = Callable[..., Any]
FieldRules = Mapping[str, Mapping[str, Rule]]


@dataclass(frozen=True, slots=True)
class Subject:
    """Where an object is available: ``available_in``, its Workspaces and its owner."""

    available_in: str
    workspace_ids: frozenset[str] = field(default_factory=frozenset)
    owner_workspace_id: str | None = None


@dataclass(frozen=True, slots=True)
class Effective:
    available: bool
    effective: dict[str, Any] | None
    deviation: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {"available": self.available, "effective": self.effective, "deviation": self.deviation}


def available(subject: Subject, workspace_id: str) -> bool:
    return (
        subject.available_in == AVAILABLE_ALL
        or workspace_id in subject.workspace_ids
        or (subject.owner_workspace_id is not None and subject.owner_workspace_id == workspace_id)
    )


def _apply(base: Mapping[str, Any], deviation: Mapping[str, Any], rules: FieldRules, *, strict: bool) -> dict:
    if not isinstance(deviation, Mapping):
        raise DeviationNotNarrowerError("deviation", "A deviation is an object of uses.")
    result = copy.deepcopy(dict(base))
    for use, values in deviation.items():
        use_rules = rules.get(use)
        if use_rules is None:
            raise DeviationNotNarrowerError(str(use), f"{use} has no deviation.")
        if not isinstance(values, Mapping):
            raise DeviationNotNarrowerError(str(use), f"{use} must be an object.")
        base_use = dict(base.get(use) or {})
        applied = dict(result.get(use) or {})
        for name, value in values.items():
            path = f"{use}.{name}"
            if name == SCHEDULE_COMPANION and SCHEDULE_FIELD in use_rules:
                continue  # read together with ``schedule``
            rule = use_rules.get(name)
            if rule is None:
                raise DeviationNotNarrowerError(path, f"{path} has no deviation.")
            if rule is narrow_schedule:
                applied.update(rule(base_use, values, path, strict=strict))
            else:
                applied[name] = rule(base_use.get(name), value, path, strict=strict)
            if name == "write_back" and isinstance(base_use.get(name), Mapping):
                applied[name] = {**base_use[name], "enabled": applied[name]}
        if SCHEDULE_COMPANION in values and SCHEDULE_FIELD not in values:
            raise DeviationNotNarrowerError(f"{use}.{SCHEDULE_COMPANION}", "schedule_cron needs schedule.")
        result[use] = applied
    return result


def check_deviation(base: Mapping[str, Any], deviation: Mapping[str, Any], rules: FieldRules) -> dict[str, Any]:
    """The effective values of a deviation that is narrower in every field; raises otherwise."""
    return _apply(base, deviation, rules, strict=True)


def effective(
    subject: Subject,
    workspace_id: str,
    base: Mapping[str, Any],
    deviation: Mapping[str, Any] | None,
    rules: FieldRules,
) -> Effective:
    """What applies in ``workspace_id`` (see the module doc); never wider than ``base``."""
    if not available(subject, workspace_id):
        return Effective(available=False, effective=None, deviation=None)
    stored = dict(deviation) if deviation else None
    values = _apply(base, stored, rules, strict=False) if stored else copy.deepcopy(dict(base))
    return Effective(available=True, effective=values, deviation=stored)


__all__ = [
    "AVAILABLE_ALL",
    "AVAILABLE_SELECTED",
    "Effective",
    "FieldRules",
    "Subject",
    "available",
    "check_deviation",
    "effective",
]
