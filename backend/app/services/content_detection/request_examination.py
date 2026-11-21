"""The examination of a whole outgoing request (the provider wrapper's) and the strict JSON both checks read.

- **one budget**: a request is examined under its one :class:`~.examination.RequestBudget` (created at the request's
  entry): every occurrence of a text counts — a duplicate is examined once but charged each time —, and once the
  budget is spent the request is unfinished, whatever was examined before (:class:`RequestExaminer`);
- **serialized JSON** (the gateway's body, a tool call's arguments) is parsed keeping every key, bounded in depth and
  finite (:func:`strict_json`): a repeated key (:class:`DuplicateKeyError`), a nesting deeper than
  :data:`MAX_DEPTH` or a non-finite number (a literal, or a token beyond the float range) is unreadable, because
  readers would disagree on what it says;
- a reported finding is remembered per scope and text with the record that reported it (:class:`Evidence`,
  :func:`digest`).
"""

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
    """A serialized JSON object names one key twice: readers disagree on its value, so it is refused."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _value in pairs]
    if len(set(keys)) != len(keys):
        raise DuplicateKeyError("a serialized object repeats a key")
    return dict(pairs)


def depth(value: Any) -> int:
    """How deep ``value`` nests (counted up to just beyond :data:`MAX_DEPTH`, without recursion)."""
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


def utf8_clean(value: Any) -> bool:
    """Whether every string (key or value) of ``value`` is valid Unicode text: an unpaired surrogate cannot be sent
    as UTF-8, so a body carrying one is unreadable (``None`` is not a body)."""
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
    """A JSON number token as a float; a valid token beyond the float range (``1e999``) decodes to infinity and is
    refused like a non-finite literal."""
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("serialized JSON carries a number beyond the float range")
    return value


def strict_json(text: str) -> Any:
    """``text`` as JSON; :class:`DuplicateKeyError` for a repeated key, ``ValueError`` for anything else (a nesting
    deeper than :data:`MAX_DEPTH`, a non-finite literal and a number that decodes to infinity included)."""
    try:
        value = json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_not_finite, parse_float=_finite)
    except RecursionError:
        raise ValueError("serialized JSON nested too deep") from None
    if depth(value) > MAX_DEPTH:
        raise ValueError("serialized JSON nested too deep")
    return value


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Evidence:
    """A bounded, process-local memo of keys (a scope and a text digest) and the decision record that established
    each (the provider wrapper: the record that reported a finding). A missing entry (a restart, an evicted key)
    means it is established again."""

    def __init__(self, size: int = EVIDENCE_SIZE) -> None:
        self.size = size
        self._keys: OrderedDict[Hashable, str] = OrderedDict()

    def remember(self, key: Hashable, record_id: str) -> None:
        self._keys[key] = record_id
        self._keys.move_to_end(key)
        while len(self._keys) > self.size:
            self._keys.popitem(last=False)

    def record(self, key: Hashable) -> str | None:
        """The id of the record that established ``key``, or ``None``."""
        return self._keys.get(key)

    def clear(self) -> None:
        self._keys.clear()


class RequestExaminer:
    """The examination of one outgoing request (see the module doc): every distinct text scanned once, every
    occurrence charged to the request's one budget. What :meth:`examine` returns is bound to the caller's source."""

    def __init__(self, detectors: DetectorSet, budget: RequestBudget) -> None:
        self.detectors = detectors
        self.budget = budget
        self._seen: dict[str, Examination] = {}

    def examine(self, text: str, source: str = SOURCE_HISTORY) -> Examination:
        seen = self._seen.get(text)
        if seen is None:
            seen = examine([Segment(text, source)], self.detectors, budget=self.budget)
            self._seen[text] = seen
        else:
            self.budget.charge(parts=1, chars=len(text))  # a repeat counts like any occurrence
            if self.budget.overrun:
                return examine([Segment(text, source)], self.detectors, budget=self.budget)
        return seen.attributed(source)

    def finished(self, segments: Iterable[Segment]) -> list[Segment]:
        """The readable ``segments`` whose examination finished: only they can select an action."""
        return [segment for segment in segments
                if segment.readable and segment.text and self.examine(segment.text, segment.source).finished]

    def report(self, segments: Sequence[Segment], detectors: frozenset[str],
               extra: Iterable[tuple[str, tuple[Finding, ...]]] = ()) -> Examination:
        """One examination of the readable ``segments`` (plus ``extra`` findings by source), restricted to
        ``detectors``; unfinished when any segment is."""
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
