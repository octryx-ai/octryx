"""The classification rules of a workflow's ``size_classes`` block, evaluated as data.

A rule is ``{"class": <name>, "when": {<condition>: <value>, ...}}``; every condition of a rule must hold, an empty
``when`` always holds, and the first rule that holds decides. The engine knows only these generic conditions; which
issue types, labels, words or counts make a class is the workflow owner's ("no hardcoding").
"""

from __future__ import annotations

import re
from typing import Any

#: A bulleted line of the description (an acceptance criterion, usually).
_BULLET = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)
CONDITIONS = frozenset({"issue_type_in", "labels_any", "labels_none", "components_any", "text_matches",
                        "text_not_matches", "criteria_min", "criteria_max", "labels_count_max",
                        "components_count_max"})


def _lower(values: Any) -> set[str]:
    return {str(value).strip().lower() for value in list(values or [])}


def facts_of(item: Any) -> dict[str, Any]:
    """What the conditions read from a work item (``None`` reads as an empty item)."""
    description = str(getattr(item, "description", None) or "")
    return {"issue_type": str(getattr(item, "issue_type", None) or "").strip().lower(),
            "labels": _lower(getattr(item, "labels_json", None)),
            "components": _lower(getattr(item, "components_json", None)),
            "text": f"{getattr(item, 'title', None) or ''}\n{description}",
            "criteria": len(_BULLET.findall(description))}


def holds(name: str, value: Any, facts: dict[str, Any]) -> bool:
    if name == "issue_type_in":
        return facts["issue_type"] in _lower(value)
    if name == "labels_any":
        return bool(facts["labels"] & _lower(value))
    if name == "labels_none":
        return not facts["labels"] & _lower(value)
    if name == "components_any":
        return bool(facts.get("components", set()) & _lower(value))
    if name == "text_matches":
        return re.search(str(value), facts["text"], re.IGNORECASE | re.MULTILINE) is not None
    if name == "text_not_matches":
        return re.search(str(value), facts["text"], re.IGNORECASE | re.MULTILINE) is None
    if name == "criteria_min":
        return facts["criteria"] >= int(value)
    if name == "criteria_max":
        return facts["criteria"] <= int(value)
    if name == "labels_count_max":
        return len(facts["labels"]) <= int(value)
    if name == "components_count_max":
        return len(facts.get("components", set())) <= int(value)
    return False


def first_match(block: dict[str, Any], item: Any) -> tuple[str, int, str]:
    """``(class, rule number from 1 or 0 for the default, what matched in words)``."""
    facts = facts_of(item)
    for number, rule in enumerate(list(block.get("rules") or []), start=1):
        when = dict(rule.get("when") or {})
        if all(holds(name, value, facts) for name, value in when.items()):
            matched = "; ".join(f"{name} {value}" for name, value in when.items()) or "any item"
            return str(rule["class"]), number, matched
    return str(block.get("default") or ""), 0, "no rule matched"


__all__ = ["CONDITIONS", "facts_of", "first_match", "holds"]
