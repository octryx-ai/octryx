"""The examination of a whole outgoing request and the strict JSON both checks read."""

from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import Any

from .examination import DOMAIN_TEXT, Examination, RequestBudget, compose, examine
from .findings import Finding
from .scanner import DetectorSet, Segment
from .vocabulary import SOURCE_HISTORY

EVIDENCE_SIZE = 16384
#: The deepest nesting a serialized request or argument may have.
MAX_DEPTH = 64


class DuplicateKeyError(ValueError):
    pass


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _value in pairs]
    if len(set(keys)) != len(keys):
        raise DuplicateKeyError("a serialized object repeats a key")
    return dict(pairs)


def depth(value: Any) -> int:
    deepest, pending = 0, [(value, 1)]
    while pending:
        item, level = pending.pop()
        deepest = max(deepest, level)
        if level > MAX_DEPTH:
            break
        if isinstance(item, Mapping):
            pending += [(child, level + 1) for child in item.values()]
        elif isinstance(item, list | tuple):
            pending += [(child, level + 1) for child in item]
    return deepest


# An unpaired surrogate cannot be sent as UTF-8, so a body carrying one is unreadable.
def utf8_clean(value: Any) -> bool:
    if value is None:
        return False
    pending = [value]
    while pending:
        item = pending.pop()
        texts = [item] if isinstance(item, str) else [key for key in item if isinstance(key, str)] if isinstance(
            item, Mapping) else []
        try:
            for text in texts:
                text.encode("utf-8")
        except UnicodeEncodeError:
            return False
        if isinstance(item, Mapping):
            pending += list(item.values())
        elif isinstance(item, list):
            pending += item
    return True


def _not_finite(name: str) -> Any:
    raise ValueError(f"serialized JSON carries the non-finite number {name}")


def _finite(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("serialized JSON carries a number beyond the float range")
    return value


# A repeated key, a nesting deeper than MAX_DEPTH or a non-finite number is refused: readers would disagree on it.
def strict_json(text: str) -> Any:
    try:
        value = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_not_finite, parse_float=_finite)
    except RecursionError:
        raise ValueError("serialized JSON nested too deep") from None
    if depth(value) > MAX_DEPTH:
        raise ValueError("serialized JSON nested too deep")
    return value


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Process-local and bounded: a missing entry (a restart, an evicted key) means the report is stated again.
class Evidence:
    def __init__(self, size: int = EVIDENCE_SIZE) -> None:
        self.size = size
        self._keys: OrderedDict[Hashable, str] = OrderedDict()

    def remember(self, key: Hashable, record_id: str) -> None:
        self._keys[key] = record_id
        self._keys.move_to_end(key)
        while len(self._keys) > self.size:
            self._keys.popitem(last=False)

    def record(self, key: Hashable) -> str | None:
        return self._keys.get(key)

    def clear(self) -> None:
        self._keys.clear()


class RequestExaminer:
    # Without a request budget each text gets the enforcement budget of its own (a tool result's masking).
    def __init__(self, detectors: DetectorSet, budget: RequestBudget | None) -> None:
        self.detectors = detectors
        self.budget = budget
        self._seen: dict[str, Examination] = {}

    def examine(self, text: str, source: str = SOURCE_HISTORY) -> Examination:
        seen = self._seen.get(text)
        if seen is None:
            seen = examine([Segment(text, source)], self.detectors, budget=self.budget)
            self._seen[text] = seen
        elif self.budget is not None:
            self.budget.charge(parts=1, chars=len(text))  # a repeat counts like any occurrence
            if self.budget.overrun:
                return examine([Segment(text, source)], self.detectors, budget=self.budget)
        return seen.attributed(source)

    def finished(self, segments: Iterable[Segment]) -> list[Segment]:
        return [segment for segment in segments
                if segment.readable and segment.text and self.examine(segment.text, segment.source).finished]

    def report(self, segments: Sequence[Segment], detectors: frozenset[str],
               extra: Iterable[tuple[str, tuple[Finding, ...]]] = ()) -> Examination:
        found: list[Examination | tuple[str, tuple[Finding, ...]]] = [
            self.examine(segment.text, segment.source) for segment in segments if segment.readable and segment.text]
        found += list(extra)
        return compose(found, domain=DOMAIN_TEXT).restricted(detectors)


__all__ = [
    "EVIDENCE_SIZE",
    "MAX_DEPTH",
    "DuplicateKeyError",
    "Evidence",
    "RequestExaminer",
    "depth",
    "digest",
    "strict_json",
    "utf8_clean",
]
