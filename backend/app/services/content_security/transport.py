"""The transport side of one model call: every text examined once and given its disposition (``model_call``).

Every text that crosses the model-call boundary is examined once per call through the shared whole-request
examination (``content_detection.request_examination.RequestExaminer``: every distinct text once, one request-wide
budget), with every shipped detector of its direction, and gets an explicit disposition before it is sent or
released (:class:`TransportRun`); the final check (``model_call_outbound``) then verifies the final request:

- **examined** (the scan finished): sent with the masked detectors' values replaced by placeholders;
- **not fully examined** (the scan stopped at its size or time budget, or a detector hit its candidate limit):
  never sent as is — the whole text is replaced by ``masking.WITHHELD_TEXT`` (``withheld``). Refusal and reporting
  read the same examination, so a text that is withheld was never judged on a partial scan either;
- **media**: only the values under the opaque key list (``content_detection.request_text``, the same list the final
  check applies: base64 media data, ``data:`` URLs) pass unread; every other field of a media block is examined;
- **unreadable** (any other content shape: a non-text, non-media block, a non-list content, a text field that is
  not text): counted (``unreadable``); the model call refuses it before dispatch, the reply before release.
"""

from __future__ import annotations

from typing import Any

from ..content_detection.examination import Examination
from ..content_detection.findings import Finding
from ..content_detection.masking import WITHHELD_TEXT, Masker, mask_text
from ..content_detection.request_examination import RequestExaminer
from ..content_detection.vocabulary import SOURCE_HISTORY


class TransportRun:
    """The disposition of every text one direction sends or releases (see the module doc). ``examinations`` holds
    the examination behind every disposition it gave (a withheld text's included), in order, for the record."""

    def __init__(self, examiner: RequestExaminer, mask: frozenset[str], masker: Masker | None = None) -> None:
        self.examiner = examiner
        self.mask = mask
        self.masker = masker or Masker()
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
        """``value`` masked as one finding (a structured credential field: the whole value is the secret)."""
        return self._masked(value, [finding]) if finding.detector in self.mask else value

    def _masked(self, value: str, findings: list[Finding]) -> str:
        if not findings:
            return value
        result = mask_text(value, findings, detectors=self.examiner.detectors, mask=self.mask, style=None,
                           masker=self.masker)
        self.masked += result.masked
        return result.text

    def withdraw_last(self) -> None:
        """The last text examined is not sent (a structure replaced its value whole)."""


__all__ = ["TransportRun"]
