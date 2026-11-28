"""Which places in a checkout a version change applies to, each with its cited fact. An element is affected only when a
change fact names it exactly."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.services.knowledge.temporal.changes_facts import ChangeFact

from .scan import (
    KIND_ANNOTATION,
    KIND_BUILD_PROPERTY,
    KIND_DEPENDENCY,
    KIND_IMPORT,
    KIND_PROPERTY,
    CodeElement,
)

MAX_LOCATIONS_PER_FACT = 25
KIND_BASELINE = "baseline"
_JAVA_LEVEL_PROPERTIES = frozenset({"java.version", "maven.compiler.release", "maven.compiler.source",
                                    "maven.compiler.target"})
_TOKEN = re.compile(r"@?[A-Za-z_][\w.\-]*\*?")
_CAMEL_WORDS = re.compile(r"[A-Z][a-z0-9]+")
_REQUIRES_JAVA = re.compile(r"\brequires Java (\d{1,2})\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ImpactItem:
    fact: ChangeFact
    locations: tuple[CodeElement, ...]
    reason: str


def _tokens(text: str) -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    prefixes: set[str] = set()
    for raw in _TOKEN.findall(text):
        token = raw.rstrip(".-")
        if token.endswith("*"):
            prefixes.add(token.rstrip("*"))
        else:
            exact.add(token)
    return exact, prefixes


def _multiword(name: str) -> bool:
    return len(_CAMEL_WORDS.findall(name)) >= 2


def _dotted_prefixes(value: str) -> list[str]:
    parts = value.split(".")
    return [".".join(parts[:end]) for end in range(len(parts) - 1, 1, -1)]


def _hits(element: CodeElement, exact: set[str], prefixes: set[str]) -> bool:
    value = element.value
    if element.kind == KIND_IMPORT:
        simple = value.rsplit(".", 1)[-1]
        # An annotation type is imported by its class name and named in prose with its ``@``.
        if value in exact or f"@{simple}" in exact or (_multiword(simple) and simple in exact):
            return True
        return any(prefix in exact for prefix in _dotted_prefixes(value.rstrip(".*")))
    if element.kind == KIND_ANNOTATION:
        return f"@{value}" in exact or (_multiword(value) and value in exact)
    if element.kind == KIND_PROPERTY:
        # A configuration key is dotted; a bare word (``database``) is prose, not a key.
        if "." not in value:
            return False
        if value in exact:
            return True
        return any(value.startswith(prefix) for prefix in prefixes if prefix.count(".") >= 2)
    if element.kind == KIND_DEPENDENCY:
        return ("-" in value or "." in value) and value in exact
    return False


def _below_baseline(element: CodeElement, required: int) -> bool:
    if element.kind != KIND_BUILD_PROPERTY or element.value not in _JAVA_LEVEL_PROPERTIES:
        return False
    level = element.detail.removeprefix("1.")
    return level.isdigit() and int(level) < required


def join_impact(facts: tuple[ChangeFact, ...], elements: tuple[CodeElement, ...]) -> tuple[ImpactItem, ...]:
    by_kind: dict[str, list[CodeElement]] = defaultdict(list)
    for element in elements:
        by_kind[element.kind].append(element)
    items: list[ImpactItem] = []
    for fact in facts:
        text = " ".join((fact.fact, fact.source_entity, fact.target_entity))
        exact, prefixes = _tokens(text)
        found: list[CodeElement] = []
        reason = "named"
        for kind in (KIND_IMPORT, KIND_ANNOTATION, KIND_PROPERTY, KIND_DEPENDENCY):
            found += [element for element in by_kind[kind] if _hits(element, exact, prefixes)]
        if (baseline := _REQUIRES_JAVA.search(fact.fact)) is not None:
            below = [element for element in by_kind[KIND_BUILD_PROPERTY] if _below_baseline(element, int(baseline[1]))]
            if below:
                found += below
                reason = KIND_BASELINE
        if found:
            items.append(ImpactItem(fact=fact, locations=tuple(found[:MAX_LOCATIONS_PER_FACT]), reason=reason))
    return tuple(items)


__all__ = ["ImpactItem", "KIND_BASELINE", "join_impact"]
