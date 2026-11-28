"""One finding of a content detector: what was found where, in memory only."""

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
    # Of overlapping spans the earliest wins, then the longest.
    kept: list[Finding] = []
    for finding in sorted(findings, key=lambda item: (item.start, -(item.end - item.start))):
        if kept and finding.start < kept[-1].end:
            continue
        kept.append(finding)
    return kept


__all__ = ["Finding", "non_overlapping"]
