"""The detector preview: what the detectors find in a sample text, as the model would see it."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .examination import examine_text
from .findings import non_overlapping
from .masking import WITHHELD_TEXT, Masker, resolve_style
from .scanner import DetectorSet
from .vocabulary import SOURCE_PROMPT

MAX_PREVIEW_CHARS = 20_000


def preview(text: str, detectors: DetectorSet, *, mask: Iterable[str] | None = None,
            style: str | None = None) -> dict[str, Any]:
    sample = text[:MAX_PREVIEW_CHARS]
    examination = examine_text(sample, SOURCE_PROMPT, detectors)
    report = examination.report
    if not examination.finished:  # never shown as checked: the sample is too large or dense to examine
        return {"summary": report.summary(), "counts": report.counts(), "masked_text": WITHHELD_TEXT, "parts": [],
                "truncated": len(text) > MAX_PREVIEW_CHARS, "unfinished": True}
    findings = list(report.findings[0]) if report.findings else []
    chosen = frozenset(mask) if mask is not None else report.detected
    masker = Masker()
    parts: list[dict[str, Any]] = []
    position = 0
    for finding in non_overlapping(findings):
        info = detectors.info(finding.detector)
        if info is None:
            continue
        if finding.start > position:
            parts.append({"text": sample[position:finding.start]})
        value = sample[finding.start:finding.end]
        masked = finding.detector in chosen
        parts.append({"text": value, "detector": finding.detector, "label": info.label, "masked": masked,
                      "placeholder": masker.placeholder(info, value, resolve_style(info, style)) if masked else None})
        position = finding.end
    if position < len(sample):
        parts.append({"text": sample[position:]})
    masked_text = "".join(part["placeholder"] or part["text"] if part.get("masked") else part["text"]
                          for part in parts)
    return {"summary": report.summary(), "counts": report.counts(), "masked_text": masked_text, "parts": parts,
            "truncated": len(text) > MAX_PREVIEW_CHARS}


__all__ = ["MAX_PREVIEW_CHARS", "preview"]
