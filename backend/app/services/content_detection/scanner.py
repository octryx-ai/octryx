"""Scan texts with a detector set inside a size and time budget."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from .builtin import CandidateLimitError, find_builtin
from .findings import Finding
from .platform_detectors import find_platform
from .stored_types import ScanSummary
from .vocabulary import BUILTIN_DETECTOR_IDS, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, DetectorInfo, builtin_detector

DEFAULT_MAX_CHARS = 2_000_000
DEFAULT_DEADLINE_MS = 50.0


class CustomMatcher(Protocol):
    id: str
    category: str
    info: DetectorInfo

    def find(self, text: str) -> list[Finding]: ...


@dataclass(frozen=True, slots=True)
class ScanBudget:
    max_chars: int = DEFAULT_MAX_CHARS
    deadline_ms: float = DEFAULT_DEADLINE_MS


# Large enough that only pathological input stays unfinished; unfinished text is withheld or refused, never passed.
ENFORCEMENT_BUDGET = ScanBudget(max_chars=16_000_000, deadline_ms=2000.0)


@dataclass(frozen=True, slots=True)
class Segment:
    text: str
    source: str
    # False for content the scan cannot read (images, base64 documents): it marks the scan incomplete.
    readable: bool = True


@dataclass(frozen=True, slots=True)
class DetectorSet:
    builtin: frozenset[str] = BUILTIN_DETECTOR_IDS
    custom: tuple[CustomMatcher, ...] = ()
    # Digest of the published detector definitions (the launcher verifies it); empty for the built-ins only.
    digest: str = ""

    def ids(self) -> frozenset[str]:
        return self.builtin | {item.id for item in self.custom}

    def info(self, detector_id: str) -> DetectorInfo | None:
        builtin = builtin_detector(detector_id)
        if builtin is not None:
            return builtin
        return next((item.info for item in self.custom if item.id == detector_id), None)


@dataclass(frozen=True, slots=True)
class ScanReport:
    scanned: bool
    complete: bool
    findings: tuple[tuple[Finding, ...], ...] = field(repr=False, default=())
    scanned_chars: int = 0
    scan_us: int = 0
    sources: tuple[str, ...] = ()
    # The source of each segment (aligned with ``findings``), so a restricted report keeps its sources right.
    segment_sources: tuple[str, ...] = field(repr=False, default=())
    # Readable text was not fully examined (size or time budget, candidate limit): its findings may be missing.
    unfinished: bool = False
    # A segment the detectors cannot read (media) was left out: the only incomplete report that is not unfinished.
    unreadable: bool = False

    def __post_init__(self) -> None:
        if self.complete and (self.unfinished or self.unreadable):
            raise ValueError("a scan that left out readable text or media is not complete")
        if not self.complete and not (self.unfinished or self.unreadable):
            raise ValueError("an incomplete scan is unfinished unless it only left out unreadable media")

    def restricted_to(self, detector_ids: frozenset[str]) -> ScanReport:
        findings = tuple(tuple(item for item in segment if item.detector in detector_ids) for segment in self.findings)
        sources = tuple(sorted({source for source, found in zip(self.segment_sources, findings, strict=False)
                                if found}))
        return replace(self, findings=findings, sources=sources)

    def all_findings(self) -> list[Finding]:
        return [finding for segment in self.findings for finding in segment]

    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(finding.detector for finding in self.all_findings()).items()))

    @property
    def detected(self) -> frozenset[str]:
        return frozenset(finding.detector for finding in self.all_findings())

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(finding.category for finding in self.all_findings())

    @property
    def total(self) -> int:
        return sum(len(segment) for segment in self.findings)

    def to_cedar(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "complete": self.complete,
            "detected": sorted(self.detected),
            "categories": sorted(self.categories),
            "findings": self.total,
            "sources": list(self.sources),
        }

    def summary(self) -> ScanSummary:
        confidence: dict[str, str] = {}
        for finding in self.all_findings():
            if confidence.get(finding.detector) != CONFIDENCE_HIGH:
                confidence[finding.detector] = finding.confidence
        kinds = sorted({finding.kind for finding in self.all_findings() if finding.kind})
        return {
            "detected": [{"id": key, "count": count, "confidence": confidence[key]}
                         for key, count in self.counts().items()],
            "categories": sorted(self.categories),
            "findings": self.total,
            "sources": list(self.sources),
            "complete": self.complete,
            "scanned_bytes": self.scanned_chars,
            "scan_us": self.scan_us,
            **({"kinds": kinds} if kinds else {}),
            **({"unfinished": True} if self.unfinished else {}),
            **({"unreadable": True} if self.unreadable else {}),
        }


EMPTY_SCAN = ScanReport(scanned=False, complete=True)


def _find(text: str, detectors: DetectorSet) -> list[Finding]:
    found = find_builtin(text, detectors.builtin) + find_platform(text, detectors.builtin)
    for matcher in detectors.custom:
        found.extend(matcher.find(text))
    return [item for item in found if item.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM)]


def scan(segments: Sequence[Segment], detectors: DetectorSet | None = None,
         budget: ScanBudget | None = None) -> ScanReport:
    detectors = detectors or DetectorSet()
    budget = budget or ScanBudget()
    started = time.perf_counter()
    deadline = started + budget.deadline_ms / 1000
    unfinished = unreadable = False
    scanned_chars = 0
    results: list[tuple[Finding, ...]] = []
    for segment in segments:
        text = segment.text or ""
        if not segment.readable or not text:
            unreadable = unreadable or not segment.readable
            results.append(())
            continue
        if scanned_chars + len(text) > budget.max_chars or time.perf_counter() >= deadline:
            unfinished = True
            results.append(())
            continue
        try:
            found = _find(text, detectors)
        except CandidateLimitError:
            unfinished, found = True, []
        scanned_chars += len(text)
        results.append(tuple(found))
    # A deadline that passed during the last detector leaves its findings in doubt: unfinished, like any overrun.
    unfinished = unfinished or time.perf_counter() > deadline
    sources = tuple(sorted({segment.source for segment, found in zip(segments, results, strict=True) if found}))
    return ScanReport(
        scanned=any(segment.text or not segment.readable for segment in segments),
        complete=not (unfinished or unreadable),
        findings=tuple(results),
        scanned_chars=scanned_chars,
        scan_us=int((time.perf_counter() - started) * 1_000_000),
        sources=sources,
        segment_sources=tuple(segment.source for segment in segments),
        unfinished=unfinished,
        unreadable=unreadable,
    )


def scan_text(text: str, source: str, detectors: DetectorSet | None = None,
              budget: ScanBudget | None = None) -> ScanReport:
    return scan([Segment(text, source)], detectors, budget)


def merge_reports(reports: Iterable[ScanReport]) -> ScanReport:
    items = list(reports)
    if not items:
        return EMPTY_SCAN
    return ScanReport(
        scanned=any(item.scanned for item in items),
        complete=all(item.complete for item in items),
        findings=tuple(segment for item in items for segment in item.findings),
        scanned_chars=sum(item.scanned_chars for item in items),
        scan_us=sum(item.scan_us for item in items),
        sources=tuple(sorted({source for item in items for source in item.sources})),
        segment_sources=tuple(source for item in items for source in item.segment_sources),
        unfinished=any(item.unfinished for item in items),
        unreadable=any(item.unreadable for item in items),
    )


__all__ = [
    "DEFAULT_DEADLINE_MS",
    "ENFORCEMENT_BUDGET",
    "DEFAULT_MAX_CHARS",
    "EMPTY_SCAN",
    "CustomMatcher",
    "DetectorSet",
    "ScanBudget",
    "ScanReport",
    "Segment",
    "merge_reports",
    "scan",
    "scan_text",
]
