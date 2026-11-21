"""Masking of a whole platform model request (governed chat) or one tool result, one masker per request.

The masker numbers values in the order they appear, and every call carries the conversation in the same order,
so earlier blocks are masked the same way on every call and the prompt cache stays stable. Only the detectors an
obligation names are masked (``obligation.mask``); everything else is left as is. Content the scan cannot read
(images, base64 documents) is not touched. A text whose examination does not finish (``Examination.finished``
false: size or time budget, candidate limit) is replaced by ``masking.WITHHELD_TEXT``: masking never passes
unexamined text. The inbound gateway masks nothing (``gateway``).

- :func:`mask_chat_messages` — OpenAI-style messages (string content or text parts);
- :func:`mask_text_value` — one text (a tool result).

Both return a new request, the number of masked values and of withheld texts; the input is never changed.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..content_detection.examination import RequestBudget, examine_text
from ..content_detection.masking import WITHHELD_TEXT, Masker, mask_text
from ..content_detection.scanner import DetectorSet
from ..content_detection.vocabulary import SOURCE_HISTORY


@dataclass(frozen=True, slots=True)
class MaskedRequest:
    body: Any
    masked: int
    withheld: int


class MaskRun:
    """One masking pass (one masker): every text of one request or result goes through :meth:`text`."""

    def __init__(self, detectors: DetectorSet, mask: frozenset[str], style: str | None,
                 masker: Masker | None = None, budget: RequestBudget | None = None) -> None:
        self.detectors = DetectorSet(detectors.builtin & mask, tuple(item for item in detectors.custom
                                                                     if item.id in mask), detectors.digest)
        self.full = detectors
        self.mask = mask
        self.style = style
        self.masker = masker or Masker()
        self.budget = budget  # the request's one budget (the model-call wrapper's), else each text's own
        self.masked = 0
        self.withheld = 0

    def text(self, value: str) -> str:
        if not value:
            return value
        examination = examine_text(value, SOURCE_HISTORY, self.detectors, budget=self.budget)
        if not examination.finished:
            self.withheld += 1
            return WITHHELD_TEXT
        if not examination.findings or not examination.findings[0]:
            return value
        result = mask_text(value, examination.findings[0], detectors=self.full, mask=self.mask, style=self.style,
                           masker=self.masker)
        self.masked += result.masked
        return result.text


def _blocks(content: Any, apply: Callable[[dict[str, Any]], None]) -> Any:
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                apply(block)
    return content


def mask_chat_messages(messages: list[Mapping[str, Any]], detectors: DetectorSet, mask: frozenset[str],
                       style: str | None, budget: RequestBudget | None = None) -> MaskedRequest:
    run = MaskRun(detectors, mask, style, budget=budget)
    changed = copy.deepcopy([dict(item) for item in messages])

    def part(block: dict[str, Any]) -> None:
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            block["text"] = run.text(block["text"])

    for message in changed:
        if isinstance(message.get("content"), str):
            message["content"] = run.text(message["content"])
        else:
            _blocks(message.get("content"), part)
    return MaskedRequest(changed, run.masked, run.withheld)


def mask_text_value(text: str, detectors: DetectorSet, mask: frozenset[str], style: str | None) -> MaskedRequest:
    """One text (a tool result)."""
    run = MaskRun(detectors, mask, style)
    return MaskedRequest(run.text(text), run.masked, run.withheld)


__all__ = ["MaskRun", "MaskedRequest", "mask_chat_messages", "mask_text_value"]
