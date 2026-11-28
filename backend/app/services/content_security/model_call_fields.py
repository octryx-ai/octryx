"""The provider wrapper's one field-aware disposition of every field of a whole model request."""

from __future__ import annotations

import json
from collections.abc import Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ..content_detection.examination import DOMAIN_FIELDS, DOMAIN_TEXT, Examination, compose
from ..content_detection.findings import Finding
from ..content_detection.request_examination import Evidence, RequestExaminer, digest
from ..content_detection.scanner import Segment
from ..content_detection.vocabulary import DETECTOR_PROMPT_INJECTION, SOURCE_HISTORY
from .handling import ACTION_REFUSE, ACTION_REPORT, HandlingPlan
from .message_trust import TRUST_AUTHORED, TRUST_UNTRUSTED, without_role_phrasing
from .model_call_masking import argument_text
from .model_call_record import SURFACE_MESSAGE_EXTRAS, SURFACE_MESSAGES, SURFACE_OFFERED_TOOLS
from .transport import TransportRun

#: The reports this process recorded: ``(scope, text digest, kind)``.
REPORTED = Evidence()
#: The surfaces where a ``refuse`` kind refuses the call when the field is new content (offered tools always are).
_REFUSING_SURFACES = frozenset({SURFACE_MESSAGES, SURFACE_MESSAGE_EXTRAS})
# In older history and replayed calls a refused kind is masked instead: that text was judged when it was new.


def structure_examination(examiner: RequestExaminer, value: Any, fields: list[Finding] | None = None) -> Examination:
    fields = [] if fields is None else fields
    readable = argument_text(value, fields)
    parts: list[Examination | tuple[str, tuple[Finding, ...]]] = [(SOURCE_HISTORY, tuple(fields))]
    if readable:
        parts.insert(0, examiner.examine(readable))
    return compose(parts, domain=DOMAIN_FIELDS)


@dataclass(frozen=True, slots=True)
class FieldExam:
    surface: str
    new: bool
    trust: str
    text: str
    examination: Examination
    structure: bool = False
    credentials: tuple[Finding, ...] = ()  # a structure's credential fields (one finding each)
    key: str = ""  # a structure's evidence text (its values included): what a report of its fields is keyed to

    def findings(self) -> Examination:
        if self.trust == TRUST_AUTHORED and not self.structure:
            return without_role_phrasing(self.examination, [Segment(self.text, SOURCE_HISTORY)])
        return self.examination


class RecordedRun(TransportRun):
    def __init__(self, examiner: RequestExaminer, mask: frozenset[str], *, keep_trust: bool = False) -> None:
        super().__init__(examiner, mask)
        self.keep_trust = keep_trust
        self.surface = SURFACE_MESSAGES
        self.new = True
        self.trust = TRUST_UNTRUSTED
        self.source = SOURCE_HISTORY  # where the current message's text is recorded (prompt, tool result, …)
        self.fields: list[FieldExam] = []
        self.credential_fields: list[Finding] = []  # of every finished structure (masked whole)
        self.withheld_at: dict[str, int] = {}
        self._last_masked = 0  # the masks of the last text

    @contextmanager
    def at(self, surface: str) -> Iterator[None]:
        previous, self.surface = self.surface, surface
        try:
            yield
        finally:
            self.surface = previous

    @contextmanager
    def message(self, *, new: bool, trust: str, source: str = SOURCE_HISTORY) -> Iterator[None]:
        previous = (self.new, self.trust, self.source)
        self.new, self.trust, self.source = new, trust, source
        try:
            yield
        finally:
            self.new, self.trust, self.source = previous

    def _withheld_here(self, count: int) -> None:
        if count:
            self.withheld_at[self.surface] = self.withheld_at.get(self.surface, 0) + count

    def text(self, value: Any, source: str | None = None) -> Any:
        examined, withheld, masked = len(self.examinations), self.withheld, self.masked
        result = super().text(value, source or self.source)
        self._last_masked = self.masked - masked
        self.fields += [FieldExam(self.surface, self.new, self.trust, value, item)
                        for item in self.examinations[examined:]]
        self._withheld_here(self.withheld - withheld)
        return result

    def withdraw_last(self) -> None:
        self.masked -= self._last_masked
        self._last_masked = 0

    def structure(self, value: Any) -> bool:
        fields: list[Finding] = []
        examination = structure_examination(self.examiner, value, fields)
        self.fields.append(FieldExam(self.surface, self.new, self.trust, argument_text(value, []), examination,
                                     structure=True, credentials=tuple(fields), key=_evidence_text(value)))
        if examination.finished:
            self.credential_fields += fields
        else:
            self.withheld += 1
            self._withheld_here(1)
        return examination.finished

    def finished(self) -> list[FieldExam]:
        return [item for item in self.fields if item.examination.finished]

    def detected(self) -> dict[str, frozenset[str]]:
        found: dict[str, frozenset[str]] = {}
        for item in self.finished():
            found[item.surface] = found.get(item.surface, frozenset()) | item.findings().detected
        return found

    @property
    def completion(self) -> Examination:
        return compose([item.examination for item in self.fields], domain=DOMAIN_TEXT).restricted(frozenset())


def _evidence_text(value: Any) -> str:
    try:
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError, RecursionError):
        return ""


def _refusing(item: FieldExam) -> bool:
    return item.surface == SURFACE_OFFERED_TOOLS or (item.new and item.surface in _REFUSING_SURFACES)


def refusing(run: RecordedRun, plan: HandlingPlan) -> tuple[Examination, Examination, dict[str, frozenset[str]]]:
    kinds = plan.kinds(ACTION_REFUSE)
    injection: list[Examination] = []
    refused: list[Examination] = []
    per_surface: dict[str, frozenset[str]] = {}
    fields = run.finished()
    in_leaves: dict[str, frozenset[str]] = {}
    in_refusing: dict[str, frozenset[str]] = {}
    for item in (item for item in fields if not item.structure):
        in_leaves[item.surface] = in_leaves.get(item.surface, frozenset()) | item.findings().detected
        if _refusing(item):
            in_refusing[item.surface] = in_refusing.get(item.surface, frozenset()) | item.findings().detected
    for item in fields:
        found = item.findings()
        counted_injection = counted_kinds = found
        if item.structure:
            counted_injection = found.restricted(found.detected - in_leaves.get(item.surface, frozenset()))
            counted_kinds = found.restricted(found.detected - in_refusing.get(item.surface, frozenset()))
        if DETECTOR_PROMPT_INJECTION in counted_injection.detected:
            injection.append(counted_injection.restricted(frozenset({DETECTOR_PROMPT_INJECTION})))
        hit = counted_kinds.detected & kinds
        if _refusing(item) and hit:
            refused.append(counted_kinds.restricted(kinds))
            per_surface[item.surface] = per_surface.get(item.surface, frozenset()) | hit
    return (compose(injection, domain=DOMAIN_TEXT), compose(refused, domain=DOMAIN_TEXT), per_surface)


@dataclass(frozen=True, slots=True)
class Reports:
    keys: dict[str, list[Hashable]]
    before: dict[str, str]


def reports(run: RecordedRun, plan: HandlingPlan, scope: Hashable) -> Reports:
    kinds = plan.kinds(ACTION_REPORT)
    keys: dict[str, list[Hashable]] = {}
    before: dict[str, str] = {}
    for item in run.finished():
        hit = ({finding.detector for finding in item.credentials if finding.detector in kinds} if item.structure
               else item.findings().detected & kinds)
        for kind in sorted(hit):
            key = (scope, digest(item.key or item.text), kind)
            earlier = REPORTED.record(key)
            if earlier is not None:
                before.setdefault(kind, earlier)
            elif key not in keys.get(kind, []):
                keys.setdefault(kind, []).append(key)
    return Reports(keys, before)


def counted(run: RecordedRun, kinds: frozenset[str]) -> list[Examination | tuple[str, tuple[Finding, ...]]]:
    seen: set[str] = set()
    found: list[Examination | tuple[str, tuple[Finding, ...]]] = []
    for item in run.finished():
        if item.structure or item.text in seen:
            continue
        seen.add(item.text)
        found.append(item.examination.restricted(kinds))
    found.append((SOURCE_HISTORY, tuple(item for item in run.credential_fields if item.detector in kinds)))
    return found


__all__ = ["REPORTED", "FieldExam", "RecordedRun", "Reports", "counted", "refusing", "reports",
           "structure_examination"]
