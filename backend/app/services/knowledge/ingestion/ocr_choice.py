"""OCR only where a PDF needs it. The text-layer decision is made in the sandbox, never by reading PDF bytes in the API
process."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

PDF_MEDIA_TYPE = "application/pdf"
PROBE_PAGES = 20
TEXT_LAYER_SHARE = 0.9
MIN_PAGE_TEXT_CHARS = 20


class OcrSetting(StrEnum):
    AUTO = "do_ocr=auto"
    OFF = "do_ocr=false"
    ON = "do_ocr=true"


def registered_version(parser_version: str, media_type: str) -> str:
    return f"{parser_version}.{OcrSetting.AUTO}" if media_type == PDF_MEDIA_TYPE else parser_version


def decided_version(parser_version: str, ocr: bool) -> str:
    return f"{parser_version}.{OcrSetting.ON if ocr else OcrSetting.OFF}"


def ocr_setting(revision_version: str, parser_version: str) -> OcrSetting | None:
    if revision_version == parser_version:
        return OcrSetting.ON  # a revision registered without a choice (not a PDF): the parser's own default
    for setting in OcrSetting:
        if revision_version == f"{parser_version}.{setting}":
            return setting
    return None


def _page_numbers(item: Mapping[str, Any]) -> set[int]:
    pages: set[int] = set()
    for provenance in item.get("prov") or ():
        if isinstance(provenance, Mapping) and type(provenance.get("page_no")) is int:
            pages.add(provenance["page_no"])
    return pages


def text_layer_share(probe: Mapping[str, Any]) -> float:
    chars: dict[int, int] = {}
    content: set[int] = set()
    for item in probe.get("texts") or ():
        if not isinstance(item, Mapping):
            continue
        length = len(str(item.get("text") or "").strip())
        for page in _page_numbers(item):
            content.add(page)
            chars[page] = chars.get(page, 0) + length
    for collection in ("pictures", "tables"):
        for item in probe.get(collection) or ():
            if isinstance(item, Mapping):
                content |= _page_numbers(item)
    if not content:
        return 0.0
    with_text = sum(1 for page in content if chars.get(page, 0) >= MIN_PAGE_TEXT_CHARS)
    return with_text / len(content)


def needs_ocr(probe: Mapping[str, Any]) -> bool:
    return text_layer_share(probe) < TEXT_LAYER_SHARE


__all__ = [
    "PROBE_PAGES",
    "TEXT_LAYER_SHARE",
    "OcrSetting",
    "decided_version",
    "needs_ocr",
    "ocr_setting",
    "registered_version",
    "text_layer_share",
]
