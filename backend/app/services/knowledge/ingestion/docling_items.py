"""DoclingDocument items read as text: references, pages, positions, tables and the shared bounds.

Part of ``docling_document.py``'s parse; a structure outside the DoclingDocument contract raises a
parser contract violation here, never a partial guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..text_safety import remove_unsafe_chars
from .parser_port import ParserError, ParserState
from .table_hyphens import document_vocabulary, repair_hyphen_breaks

MAX_DOCUMENT_NODES = 200_000
MAX_TREE_DEPTH = 64
MAX_SECTION_DEPTH = 6
MAX_HEADING_CHARS = 200
# A list of at least this many entries, nearly all links to the same site, is navigation
# (``docling_walk._Walker._is_site_navigation``).
NAVIGATION_MIN_ITEMS = 20
NAVIGATION_LINK_SHARE = 0.9

_COLLECTIONS = frozenset({"texts", "tables", "groups", "pictures", "key_value_items", "form_items"})
_SKIPPED_LABELS = frozenset({"page_header", "page_footer", "document_index", "key_value_region", "form"})
_TEXT_LABELS = frozenset(
    {"text", "paragraph", "caption", "footnote", "reference", "formula", "checkbox_selected",
     "checkbox_unselected", "handwritten_text"}
)
# Vendor admonition boxes Docling reports as headings; an optional leading symbol (the manuals render it as
# a glyph such as "®", "Ϫ" or a letter "b"), then the marker, then nothing or a short label ("Example 3").
ADMONITION_MARKERS: tuple[str, ...] = ("Note", "Caution", "Tip", "Warning", "Important", "Example")
MAX_ADMONITION_CHARS = 40


def _admonition_pattern(markers: tuple[str, ...]) -> re.Pattern[str]:
    words = "|".join(re.escape(marker) for marker in markers)
    return re.compile(rf"^(?:\S{{1,2}}\s+)?(?:{words})s?(?:\s*[:\-–]\s*(?:\S.*)?|\s+\d.*)?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Block:
    kind: str
    text: str
    page: int | None
    section_path: tuple[str, ...]
    top: float | None = None  # distance from the page's top edge, for the outline lookup


def _contract(reason: str) -> ParserError:
    return ParserError(ParserState.CONTRACT_VIOLATION, reason)


def _clean(text: object, *, keep_lines: bool = False) -> str:
    if type(text) is not str:
        return ""
    if keep_lines:
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
        return remove_unsafe_chars("\n".join(lines).strip("\n"), allow_line_breaks=True)
    return remove_unsafe_chars(" ".join(text.split()), allow_line_breaks=False)


def _page(item: dict[str, Any]) -> int | None:
    provenance = item.get("prov")
    if isinstance(provenance, list) and provenance and isinstance(provenance[0], dict):
        page = provenance[0].get("page_no")
        if type(page) is int and page >= 1:
            return page
    return None


def _top(item: dict[str, Any], pages: object) -> float | None:
    provenance = item.get("prov")
    first = provenance[0] if isinstance(provenance, list) and provenance and isinstance(provenance[0], dict) else {}
    bbox, page = first.get("bbox"), first.get("page_no")
    if not isinstance(bbox, dict) or type(bbox.get("t")) not in (int, float):
        return None
    if bbox.get("coord_origin") == "TOPLEFT":
        return float(bbox["t"])
    size = pages.get(str(page), {}).get("size") if isinstance(pages, dict) else None
    height = size.get("height") if isinstance(size, dict) else None
    return max(0.0, float(height) - float(bbox["t"])) if type(height) in (int, float) else None


def _table_text(item: dict[str, Any], vocabulary: frozenset[str] = frozenset()) -> str:
    data = item.get("data")
    grid = data.get("grid") if isinstance(data, dict) else None
    if not isinstance(grid, list):
        return ""
    rows: list[str] = []
    for row in grid:
        if not isinstance(row, list):
            raise _contract("table_grid")
        seen: set[tuple[object, object]] = set()
        cells: list[str] = []
        for cell in row:
            if not isinstance(cell, dict):
                raise _contract("table_cell")
            # A spanning cell is repeated in every grid position it covers; render it once.
            origin = (cell.get("start_row_offset_idx"), cell.get("start_col_offset_idx"))
            if origin in seen:
                continue
            seen.add(origin)
            raw = cell.get("text")
            cells.append(_clean(repair_hyphen_breaks(raw, vocabulary) if type(raw) is str else raw))
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _vocabulary(document: dict[str, Any]) -> frozenset[str]:
    texts = [item.get("text") for item in document.get("texts") or () if isinstance(item, dict)]
    for table in document.get("tables") or ():
        data = table.get("data") if isinstance(table, dict) else None
        cells = data.get("table_cells") if isinstance(data, dict) else None
        texts.extend(cell.get("text") for cell in cells or () if isinstance(cell, dict))
    return document_vocabulary(text for text in texts if type(text) is str)
