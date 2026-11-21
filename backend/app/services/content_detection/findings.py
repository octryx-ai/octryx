"""One finding of a content detector: what was found where — in memory only.

A :class:`Finding` carries the span so the masker can replace it; it has no serializer and its ``repr`` names
the detector only. Everything that leaves the process (decision log, audit, transcripts, API answers) is the
scan *summary* (``scanner.ScanReport.summary``): detector ids, categories, counts, sources.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    detector: str
    category: str
    confidence: str
    start: int
    end: int
    # The secret scanner's fixed kind (``private_key``, ``jwt``, …) for the ``secrets`` detector; else empty.
    kind: str = ""

    def __repr__(self) -> str:  # never the span: a log line must not locate the value
        return f"Finding({self.detector}, {self.confidence})"

    def overlaps(self, other: Finding) -> bool:
        return self.start < other.end and other.start < self.end


def non_overlapping(findings: list[Finding]) -> list[Finding]:
    """The findings to mask, in text order: of overlapping spans the earliest, then the longest wins."""
    kept: list[Finding] = []
    for finding in sorted(findings, key=lambda item: (item.start, -(item.end - item.start))):
        if kept and finding.start < kept[-1].end:
            continue
        kept.append(finding)
    return kept


__all__ = ["Finding", "non_overlapping"]
