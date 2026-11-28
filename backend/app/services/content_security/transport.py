"""The transport side of one model call: every text examined once and given its disposition."""

from __future__ import annotations

from typing import Any

from ..content_detection.examination import Examination, RequestBudget
from ..content_detection.findings import Finding
from ..content_detection.masking import WITHHELD_TEXT, Masker, PlaceholderSpans, mask_text
from ..content_detection.request_examination import RequestExaminer
from ..content_detection.scanner import DetectorSet
from ..content_detection.vocabulary import SOURCE_HISTORY


class TransportRun:
    # ``style`` and ``naming``: a policy's mask style, and the detectors its placeholders are named by (a mask run
    # examines only the kinds it masks); every placeholder written is kept for the checks after it.
    def __init__(self, examiner: RequestExaminer, mask: frozenset[str], masker: Masker | None = None, *,
                 style: str | None = None, naming: DetectorSet | None = None) -> None:
        self.examiner = examiner
        self.mask = mask
        self.masker = masker or Masker()
        self.style = style
        self.naming = naming or examiner.detectors
        self.placeholders = PlaceholderSpans()
        self.masked = 0
        self.withheld = 0
        self.unreadable = 0
        self.examinations: list[Examination] = []

    def text(self, value: Any, source: str = SOURCE_HISTORY) -> Any:
        if not isinstance(value, str):
            self.unreadable += 1
            return value
        if not value:
            return value
        examination = self.examiner.examine(value, source)
        self.examinations.append(examination)
        if not examination.finished:
            self.withheld += 1
            return WITHHELD_TEXT
        return self._masked(value, [item for item in examination.findings[0] if item.detector in self.mask])

    def whole(self, value: str, finding: Finding) -> str:
        return self._masked(value, [finding]) if finding.detector in self.mask else value

    def _masked(self, value: str, findings: list[Finding]) -> str:
        if not findings:
            return value
        result = mask_text(value, findings, detectors=self.naming, mask=self.mask, style=self.style,
                           masker=self.masker)
        self.masked += result.masked
        self.placeholders.add(result)
        return result.text

    def withdraw_last(self) -> None:
        pass


# A run that masks the kinds a policy names in its style: it examines only those kinds.
def mask_run(detectors: DetectorSet, mask: frozenset[str], style: str | None, *, masker: Masker | None = None,
             budget: RequestBudget | None = None) -> TransportRun:
    examined = DetectorSet(detectors.builtin & mask, tuple(item for item in detectors.custom if item.id in mask),
                           detectors.digest)
    return TransportRun(RequestExaminer(examined, budget), mask, masker, style=style, naming=detectors)


__all__ = ["TransportRun", "mask_run"]
