"""The one examination contract every consumer of a content scan goes through."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from .findings import Finding
from .masking import PlaceholderSpans
from .scanner import ENFORCEMENT_BUDGET, DetectorSet, ScanBudget, ScanReport, Segment, merge_reports, scan

DOMAIN_TEXT = "text"
DOMAIN_STRUCTURED = "structured"
DOMAIN_FIELDS = "fields"
DOMAINS = frozenset({DOMAIN_TEXT, DOMAIN_STRUCTURED, DOMAIN_FIELDS})

DISPOSITION_ALLOW = "allow"
DISPOSITION_MASK = "mask"
DISPOSITION_WITHHOLD = "withhold"
DISPOSITION_REFUSE = "refuse"
DISPOSITION_REVIEW = "review"
DISPOSITIONS = frozenset({DISPOSITION_ALLOW, DISPOSITION_MASK, DISPOSITION_WITHHOLD, DISPOSITION_REFUSE,
                          DISPOSITION_REVIEW})
INCOMPLETE_DISPOSITIONS = frozenset({DISPOSITION_WITHHOLD, DISPOSITION_REFUSE, DISPOSITION_REVIEW})

_FACTORY = object()
#: The most parts (texts and media) one outgoing request may carry into its examination.
MAX_REQUEST_PARTS = 20_000
#: The one deadline of an outgoing request's content examination, from its entry to its last scan.
REQUEST_DEADLINE_MS = 10_000.0


class IncompleteExaminationError(ValueError):
    pass


class _Immutable:
    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __copy__(self) -> _Immutable:
        return self

    def __deepcopy__(self, memo: dict) -> _Immutable:
        return self

    def __reduce__(self) -> object:
        raise TypeError(f"{type(self).__name__} is built only by its factory")


class Examination(_Immutable):
    __slots__ = ("domain", "report")
    report: ScanReport
    domain: str

    def __init__(self, report: ScanReport, domain: str, token: object) -> None:
        if token is not _FACTORY:
            raise TypeError("an Examination is built only by examine(), examine_text() or compose()")
        if domain not in DOMAINS:
            raise ValueError(f"unknown examination domain: {domain}")
        if not isinstance(report, ScanReport):
            raise TypeError("an Examination holds a ScanReport")
        object.__setattr__(self, "report", report)
        object.__setattr__(self, "domain", domain)

    @property
    def finished(self) -> bool:
        report = self.report
        return report.complete or (report.unreadable and not report.unfinished)

    @property
    def findings(self) -> tuple[tuple[Finding, ...], ...]:
        return self.report.findings

    @property
    def detected(self) -> frozenset[str]:
        return self.report.detected

    def restricted(self, detector_ids: frozenset[str]) -> Examination:
        return Examination(self.report.restricted_to(detector_ids), self.domain, _FACTORY)

    def excluding(self, drop: Callable[[int, Finding], bool]) -> Examination:
        return Examination(_without(self.report, drop), self.domain, _FACTORY)

    # The part [start, end) of a one-text examination as if that part had been examined alone: its findings, shifted to
    # the part (``padding``: the brackets a list part gets when it is written alone), its size and its source.
    def within(self, start: int, end: int, source: str, *, padding: int = 0) -> Examination:
        report = self.report
        whole = report.findings[0] if report.findings else ()
        found = tuple(replace(item, start=item.start - start + padding, end=item.end - start + padding)
                      for item in whole if start <= item.start and item.end <= end)
        size = end - start + 2 * padding
        part = ScanReport(scanned=report.scanned and size > 0, complete=report.complete, findings=(found,),
                          scanned_chars=0 if report.unfinished else size, sources=(source,) if found else (),
                          segment_sources=(source,), unfinished=report.unfinished, unreadable=report.unreadable)
        return Examination(part, self.domain, _FACTORY)

    def attributed(self, source: str) -> Examination:
        report = self.report
        if set(report.segment_sources) <= {source}:
            return self
        sources = (source,) if any(report.findings) else ()
        return Examination(replace(report, segment_sources=tuple(source for _ in report.segment_sources),
                                   sources=sources), self.domain, _FACTORY)

    def permits(self, allowed: bool) -> bool:
        return bool(allowed) and self.finished

    def disposition(self, *, allowed: bool, incomplete: str, masks: bool = False) -> str:
        if incomplete not in INCOMPLETE_DISPOSITIONS:
            raise ValueError(f"an incomplete examination cannot be '{incomplete}'")
        if not self.finished:
            return incomplete
        if not allowed:
            return DISPOSITION_REFUSE
        return DISPOSITION_MASK if masks else DISPOSITION_ALLOW

    def clean_entry(self, *scope: object) -> CleanEntry:
        if not self.clean:
            raise IncompleteExaminationError("only a finished examination without findings is clean")
        return CleanEntry(self, scope, _FACTORY)

    @property
    def clean(self) -> bool:
        return self.finished and not self.report.total


class CleanEntry(_Immutable):
    __slots__ = ("examination", "key")
    examination: Examination
    key: tuple

    def __init__(self, examination: Examination, scope: tuple, token: object) -> None:
        if token is not _FACTORY:
            raise TypeError("a CleanEntry comes only from Examination.clean_entry()")
        object.__setattr__(self, "examination", examination)
        object.__setattr__(self, "key", (examination.domain, *scope))

    @property
    def proven(self) -> bool:
        examination = self.examination
        return (isinstance(examination, Examination) and examination.clean and examination.domain in DOMAINS
                and bool(self.key) and self.key[0] == examination.domain)


# Keyed by domain (text, structured, fields): a clean text never vouches for a structure or a field-aware examination.
class CleanCache:
    def __init__(self, size: int) -> None:
        self.size = size
        self._entries: OrderedDict[tuple, bool] = OrderedDict()

    def remember(self, entry: CleanEntry) -> None:
        if not isinstance(entry, CleanEntry):
            raise TypeError("only a CleanEntry from a finished, finding-free examination is cached")
        if not entry.proven:
            raise IncompleteExaminationError("a clean entry whose examination is not clean in its domain")
        self._entries[entry.key] = True
        self._entries.move_to_end(entry.key)
        while len(self._entries) > self.size:
            self._entries.popitem(last=False)

    def holds(self, domain: str, *scope: object) -> bool:
        if domain not in DOMAINS:
            raise ValueError(f"unknown examination domain: {domain}")
        return (domain, *scope) in self._entries

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


# Bounds the content examination only: admission, budget and commit steps after a finished examination are not content
# work.
class RequestBudget:
    def __init__(self, *, max_chars: int | None = None, deadline_ms: float | None = None,
                 max_parts: int | None = None) -> None:
        self.max_chars = min(max_chars or ENFORCEMENT_BUDGET.max_chars, ENFORCEMENT_BUDGET.max_chars)
        self.max_parts = max_parts or MAX_REQUEST_PARTS
        self.deadline = time.monotonic() + (deadline_ms or REQUEST_DEADLINE_MS) / 1000
        self.chars = 0
        self.parts = 0
        self._exceeded = False

    def charge(self, *, parts: int = 0, chars: int = 0) -> None:
        self.parts += parts
        self.chars += chars
        self._exceeded = self._exceeded or self.parts > self.max_parts or self.chars > self.max_chars

    @property
    def overrun(self) -> bool:
        return self._exceeded or time.monotonic() >= self.deadline

    def remainder(self) -> ScanBudget | None:
        if self.overrun:
            return None
        return ScanBudget(max_chars=self.max_chars, deadline_ms=(self.deadline - time.monotonic()) * 1000)


def _with_findings(report: ScanReport, findings: tuple[tuple[Finding, ...], ...]) -> ScanReport:
    sources = tuple(sorted({source for source, found in zip(report.segment_sources, findings, strict=False) if found}))
    return replace(report, findings=findings, sources=sources)


def _without(report: ScanReport, drop: Callable[[int, Finding], bool]) -> ScanReport:
    return _with_findings(report, tuple(tuple(item for item in found if not drop(index, item))
                                        for index, found in enumerate(report.findings)))


def _unscanned(segments: Sequence[Segment]) -> ScanReport:
    return ScanReport(scanned=True, complete=False, findings=tuple(() for _ in segments),
                      segment_sources=tuple(segment.source for segment in segments), unfinished=True)


def _within(segments: Sequence[Segment], detectors: DetectorSet, budget: RequestBudget,
            placeholders: PlaceholderSpans | None = None) -> ScanReport:
    remainder = budget.remainder()
    if remainder is None:
        return _unscanned(segments)
    report = scan(segments, detectors, remainder)
    if budget.overrun:
        return _unscanned(segments)
    if placeholders is not None:
        kept: list[tuple[Finding, ...]] = []
        for index, found in enumerate(report.findings):
            outside = placeholders.outside(segments[index].text, found, lambda: budget.overrun)
            if outside is None:
                return _unscanned(segments)
            kept.append(outside)
        report = _with_findings(report, tuple(kept))
    return _unscanned(segments) if budget.overrun else report


def _scan(segments: Sequence[Segment], detectors: DetectorSet, budget: RequestBudget | None,
          placeholders: PlaceholderSpans | None = None) -> ScanReport:
    if budget is None:
        return scan(segments, detectors, ENFORCEMENT_BUDGET)
    budget.charge(parts=len(segments), chars=sum(len(segment.text or "") for segment in segments
                                                 if segment.readable))
    return _within(segments, detectors, budget, placeholders)


def examine(segments: Sequence[Segment], detectors: DetectorSet, *, domain: str = DOMAIN_TEXT,
            budget: RequestBudget | None = None, placeholders: PlaceholderSpans | None = None) -> Examination:
    if placeholders is not None and budget is None:
        raise ValueError("a placeholder filter runs only under a request budget")
    return Examination(_scan(segments, detectors, budget, placeholders), domain, _FACTORY)


def examine_text(text: str, source: str, detectors: DetectorSet, *, domain: str = DOMAIN_TEXT,
                 budget: RequestBudget | None = None) -> Examination:
    return examine([Segment(text, source)], detectors, domain=domain, budget=budget)


def examine_pass(text: str, source: str, detectors: DetectorSet, budget: RequestBudget) -> Examination:
    # Charges nothing: the final check charged the request's full serialized size to the cap before this pass.
    return Examination(_within([Segment(text, source)], detectors, budget), DOMAIN_TEXT, _FACTORY)


def compose(parts: Iterable[Examination | tuple[str, tuple[Finding, ...]]], *, domain: str) -> Examination:
    reports: list[ScanReport] = []
    derived: list[tuple[str, tuple[Finding, ...]]] = []
    for part in parts:
        if isinstance(part, Examination):
            reports.append(part.report)
        elif part[1]:
            derived.append(part)
    if derived:
        reports.append(ScanReport(scanned=True, complete=True, findings=tuple(found for _source, found in derived),
                                  sources=tuple(sorted({source for source, _found in derived})),
                                  segment_sources=tuple(source for source, _found in derived)))
    if not reports:
        return Examination(ScanReport(scanned=False, complete=True), domain, _FACTORY)
    # merge_reports keeps the result unfinished when any part is.
    return Examination(merge_reports(reports), domain, _FACTORY)


__all__ = [
    "DISPOSITIONS",
    "DISPOSITION_ALLOW",
    "DISPOSITION_MASK",
    "DISPOSITION_REFUSE",
    "DISPOSITION_REVIEW",
    "DISPOSITION_WITHHOLD",
    "DOMAINS",
    "DOMAIN_FIELDS",
    "DOMAIN_STRUCTURED",
    "DOMAIN_TEXT",
    "INCOMPLETE_DISPOSITIONS",
    "MAX_REQUEST_PARTS",
    "REQUEST_DEADLINE_MS",
    "CleanCache",
    "CleanEntry",
    "Examination",
    "IncompleteExaminationError",
    "RequestBudget",
    "compose",
    "examine",
    "examine_pass",
    "examine_text",
]
