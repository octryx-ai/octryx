"""The one examination contract every consumer of a content scan goes through.

The budgeted scanner (``scanner.scan``) is called here and nowhere else (``tests/content_security/
test_examination_contract.py`` enumerates every call site). What a consumer gets is an :class:`Examination`:

- built only by the factories :func:`examine`, :func:`examine_text`, :func:`examine_each`, :func:`examine_pass`
  and :func:`compose` (the constructor refuses any other caller), always within :data:`scanner.ENFORCEMENT_BUDGET`
  — or within the remainder of a :class:`RequestBudget`, the one budget of a whole outgoing request (a deadline
  from its entry, a cap on each pass's characters, a parts limit); a request whose budget is spent gets unfinished
  examinations, never a scan beyond it;
- ``finished`` means the scan is ``complete``, or incomplete only by the explicit media exemption
  (``unreadable`` and not ``unfinished``). The report itself has no third state (``ScanReport.__post_init__``): an
  incomplete report is unfinished unless it is the media exemption, and a deadline overrun is always unfinished;
- immutable: an examination's report and domain, and a clean entry's proof, cannot be reassigned after the factory
  built them;
- an allow can only come from :meth:`Examination.permits` / :meth:`Examination.disposition`: an unfinished
  examination never permits, whatever a Workspace (Cedar) policy answered;
- a clean-cache entry can only come from :meth:`Examination.clean_entry`, which refuses an unfinished examination
  or one with findings; :class:`CleanCache` accepts nothing else and re-checks the proof (the entry's examination
  finished without findings, and its key names that examination's domain);
- :meth:`Examination.attributed` re-binds a memoized examination to the source of the segment it is recorded for
  (a per-call memo scans each distinct text once, whatever source it appears under).

Examination **domains** keep cache entries apart: ``text`` (a text as text), ``structured`` (the aggregate
serialized text of a structure) and ``fields`` (field-aware: field names with their values). A clean entry is
keyed by its domain, so a text-domain clean result never suppresses a structured or field-aware examination.

Dispositions (:data:`DISPOSITIONS`): ``allow``, ``mask``, ``withhold``, ``refuse``, ``review``. An unfinished
examination gets the consumer's incomplete disposition, which must be ``withhold``, ``refuse`` or ``review``.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from .findings import Finding
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
    """An allow or a clean entry was asked of an examination that did not finish (or found something)."""


class _Immutable:
    """Attributes are set once, by the constructor (``object.__setattr__``); never reassigned or deleted."""

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
    """A finished-or-not scan result with its domain (see the module doc)."""

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
        """The same examination with only the findings of ``detector_ids`` (its completion unchanged)."""
        return Examination(self.report.restricted_to(detector_ids), self.domain, _FACTORY)

    def excluding(self, drop: Callable[[int, Finding], bool]) -> Examination:
        """The same examination without the findings ``drop(segment_index, finding)`` names (completion unchanged)."""
        findings = tuple(tuple(item for item in found if not drop(index, item))
                         for index, found in enumerate(self.report.findings))
        sources = tuple(sorted({source for source, found in zip(self.report.segment_sources, findings, strict=False)
                                if found}))
        return Examination(replace(self.report, findings=findings, sources=sources), self.domain, _FACTORY)

    def attributed(self, source: str) -> Examination:
        """The same examination with every segment recorded under ``source`` (completion and findings unchanged)."""
        report = self.report
        if set(report.segment_sources) <= {source}:
            return self
        sources = (source,) if any(report.findings) else ()
        return Examination(replace(report, segment_sources=tuple(source for _ in report.segment_sources),
                                   sources=sources), self.domain, _FACTORY)

    def permits(self, allowed: bool) -> bool:
        """``allowed`` (a policy's answer) only when the examination finished."""
        return bool(allowed) and self.finished

    def disposition(self, *, allowed: bool, incomplete: str, masks: bool = False) -> str:
        """The disposition: ``incomplete`` when unfinished, else allow / mask / refuse per the policy's answer."""
        if incomplete not in INCOMPLETE_DISPOSITIONS:
            raise ValueError(f"an incomplete examination cannot be '{incomplete}'")
        if not self.finished:
            return incomplete
        if not allowed:
            return DISPOSITION_REFUSE
        return DISPOSITION_MASK if masks else DISPOSITION_ALLOW

    def clean_entry(self, *scope: object) -> CleanEntry:
        """The proof that this examination finished and found nothing, for :class:`CleanCache`."""
        if not self.clean:
            raise IncompleteExaminationError("only a finished examination without findings is clean")
        return CleanEntry(self, scope, _FACTORY)

    @property
    def clean(self) -> bool:
        return self.finished and not self.report.total


class CleanEntry(_Immutable):
    """A clean-cache key with its proof (the clean examination), obtainable only from
    :meth:`Examination.clean_entry`."""

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
        """The proof holds: a clean examination, and the key names its domain."""
        examination = self.examination
        return (isinstance(examination, Examination) and examination.clean and examination.domain in DOMAINS
                and bool(self.key) and self.key[0] == examination.domain)


class CleanCache:
    """An LRU of clean entries; looked up by domain and scope."""

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


class RequestBudget:
    """The one budget of a whole outgoing request (I-3), created when the request enters (the gateway reading its
    body, the provider wrapper receiving the call):

    - one deadline (:data:`REQUEST_DEADLINE_MS` from entry) over the content examination, up to its last scan (the
      provider wrapper: the final-bytes check, ``final_check``, its serialization included); admission, budget and
      commit steps after a finished examination are not content work and are not bounded by it;
    - a cap of :data:`ENFORCEMENT_BUDGET` characters on each pass over the request: the examination of its parts —
      every occurrence counts, a duplicate included — and the final-bytes check of the serialized request (its full
      byte length, opaque values included);
    - at most :data:`MAX_REQUEST_PARTS` parts.

    Once the deadline passed or a cap was exceeded the request is unfinished (:attr:`overrun`), whatever was
    examined before: every later scan is unfinished and the final-bytes check refuses it."""

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
        """What one more scan may use; ``None`` when the request's budget is spent."""
        if self.overrun:
            return None
        return ScanBudget(max_chars=self.max_chars, deadline_ms=(self.deadline - time.monotonic()) * 1000)


def _unscanned(segments: Sequence[Segment]) -> ScanReport:
    """The report of segments a spent request budget left unexamined."""
    return ScanReport(scanned=True, complete=False, findings=tuple(() for _ in segments),
                      segment_sources=tuple(segment.source for segment in segments), unfinished=True)


def _within(segments: Sequence[Segment], detectors: DetectorSet, budget: RequestBudget) -> ScanReport:
    remainder = budget.remainder()
    if remainder is None:
        return _unscanned(segments)
    report = scan(segments, detectors, remainder)
    return _unscanned(segments) if budget.overrun else report  # the deadline passed during the scan


def _scan(segments: Sequence[Segment], detectors: DetectorSet, budget: RequestBudget | None) -> ScanReport:
    if budget is None:
        return scan(segments, detectors, ENFORCEMENT_BUDGET)
    budget.charge(parts=len(segments), chars=sum(len(segment.text or "") for segment in segments
                                                 if segment.readable))
    return _within(segments, detectors, budget)


def examine(segments: Sequence[Segment], detectors: DetectorSet, *, domain: str = DOMAIN_TEXT,
            budget: RequestBudget | None = None) -> Examination:
    """``segments`` scanned with ``detectors`` inside the enforcement budget (or what ``budget`` has left)."""
    return Examination(_scan(segments, detectors, budget), domain, _FACTORY)


def examine_each(segments: Sequence[Segment], detectors: DetectorSet, budget: RequestBudget) -> tuple[Examination, ...]:
    """One scan of every segment of a request (one budget), as one examination per segment. A segment is finished
    only when the whole scan finished: an unfinished scan leaves every segment unfinished."""
    report = _scan(segments, detectors, budget)
    each: list[Examination] = []
    for index, segment in enumerate(segments):
        found = report.findings[index] if index < len(report.findings) else ()
        media = not segment.readable
        part = ScanReport(scanned=bool(segment.text) or media, complete=not (report.unfinished or media),
                          findings=(found,), scanned_chars=len(segment.text or "") if segment.readable else 0,
                          scan_us=report.scan_us if index == 0 else 0,
                          sources=(segment.source,) if found else (), segment_sources=(segment.source,),
                          unfinished=report.unfinished, unreadable=media)
        each.append(Examination(part, DOMAIN_TEXT, _FACTORY))
    return tuple(each)


def examine_text(text: str, source: str, detectors: DetectorSet, *, domain: str = DOMAIN_TEXT,
                 budget: RequestBudget | None = None) -> Examination:
    return examine([Segment(text, source)], detectors, domain=domain, budget=budget)


def examine_pass(text: str, source: str, detectors: DetectorSet, budget: RequestBudget) -> Examination:
    """A further pass over the whole request as one text (the final-bytes check, which charges the request's full
    serialized size to the cap first): within the request's deadline."""
    return Examination(_within([Segment(text, source)], detectors, budget), DOMAIN_TEXT, _FACTORY)


def compose(parts: Iterable[Examination | tuple[str, tuple[Finding, ...]]], *, domain: str) -> Examination:
    """One examination of several: examinations, plus ``(source, findings)`` a consumer derived itself (a
    structured credential field). Unfinished when any part is, never complete then."""
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
    "examine_each",
    "examine_pass",
    "examine_text",
]
