"""Savings hints: the catalog's rules (``token_rules.json``) evaluated against the facts of each scope (pure)."""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

from .catalog import rules as catalog_rules
from .facts import SCOPES

_OPS: dict[str, Callable[[Any, Any], bool]] = {">=": operator.ge, ">": operator.gt, "<=": operator.le,
                                               "<": operator.lt, "==": operator.eq}


def _matches(rule: dict[str, Any], fact: dict[str, Any]) -> bool:
    for name, allowed in (rule.get("match") or {}).items():
        if fact.get(name) not in allowed:
            return False
    for name, tests in (rule.get("when") or {}).items():
        value = fact.get(name)
        if not isinstance(value, (int, float)):
            return False
        if not all(op in _OPS and _OPS[op](value, limit) for op, limit in tests.items()):
            return False
    return True


def _shown(fact: dict[str, Any]) -> dict[str, str]:
    return {name: f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else str(value)
            for name, value in fact.items()}


def hints(pairs: list[Any], rules: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    facts = {scope: build(pairs) for scope, build in SCOPES.items()}
    for rule in catalog_rules() if rules is None else rules:
        for fact in facts.get(str(rule.get("scope") or ""), []):
            if not _matches(rule, fact):
                continue
            try:
                text = str(rule.get("text") or "").format_map(_shown(fact))
            except (KeyError, ValueError):
                continue  # a rule naming a fact its scope does not have shows nothing rather than a broken line
            weight = fact.get(str(rule.get("tokens_from") or "tokens"))
            found.append({"rule": rule.get("id"), "text": text,
                          "tokens": weight if isinstance(weight, int) and not isinstance(weight, bool) else 0,
                          "phase": str(fact.get("phase") or ""), "estimated": bool(fact.get("estimated"))})
    return sorted(found, key=lambda hint: -hint["tokens"])


__all__ = ["hints"]
