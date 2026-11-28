"""Element paths, selectors, property values and the closed failure codes of the Office engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

ELEMENT_NOT_FOUND = "office_element_not_found"
UNSUPPORTED_ELEMENT = "office_unsupported_element"
INVALID_REQUEST = "office_invalid_request"
DOCUMENT_UNREADABLE = "office_document_unreadable"
FILE_NOT_FOUND = "office_file_not_found"


class OfficeEngineError(Exception):
    def __init__(self, code: str, fact: str = "") -> None:
        super().__init__(f"{code} {fact}".strip())
        self.code = code
        self.fact = fact

    def as_result(self) -> dict[str, Any]:
        return {"error": str(self), "error_code": self.code}


@dataclass(frozen=True, slots=True)
class Segment:
    name: str
    index: int | None = None
    key: str = ""


_SEGMENT = re.compile(r"^(?P<name>[A-Za-z_][\w.-]*)(?:\[(?P<inner>[^\]]*)\])?$")


def parse_path(path: str) -> list[Segment]:
    raw = str(path or "").strip()
    if not raw.startswith("/"):
        raise OfficeEngineError(INVALID_REQUEST, "path must start with /")
    segments: list[Segment] = []
    for token in [part for part in raw.split("/") if part]:
        match = _SEGMENT.match(token)
        if not match:
            segments.append(Segment(token))
            continue
        inner = (match.group("inner") or "").strip()
        if inner.isdigit():
            index = int(inner)
            if index < 1:
                raise OfficeEngineError(INVALID_REQUEST, "path indices are 1-based")
            segments.append(Segment(match.group("name"), index))
        else:
            segments.append(Segment(match.group("name"), None, inner))
    return segments


@dataclass(frozen=True, slots=True)
class Selector:
    element_type: str
    filters: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    contains: str = ""


_SELECTOR = re.compile(r"^(?P<type>[A-Za-z_*][\w-]*)(?P<filters>(?:\[[^\]]+\])*)(?::contains\((?P<text>.*)\))?$")
_FILTER = re.compile(r"\[(?P<attr>[\w.-]+)\s*(?P<op>~=|!=|=)\s*(?P<value>[^\]]*)\]")

#: Selector type names → the ``type`` an element descriptor carries.
TYPE_ALIASES = {
    "p": "paragraph",
    "para": "paragraph",
    "tbl": "table",
    "tr": "row",
    "tc": "cell",
    "r": "run",
    "pic": "picture",
    "image": "picture",
    "sp": "shape",
}


def parse_selector(selector: str) -> Selector:
    match = _SELECTOR.match(str(selector or "").strip())
    if not match:
        raise OfficeEngineError(INVALID_REQUEST, "unsupported selector")
    filters = tuple(
        (item.group("attr"), item.group("op"), item.group("value").strip().strip("'\""))
        for item in _FILTER.finditer(match.group("filters") or "")
    )
    element_type = match.group("type").lower()
    return Selector(TYPE_ALIASES.get(element_type, element_type), filters, (match.group("text") or "").strip("'\""))


def selector_matches(selector: Selector, descriptor: dict[str, Any]) -> bool:
    if selector.element_type not in {"*", str(descriptor.get("type") or "")}:
        return False
    for attr, op, expected in selector.filters:
        # Spaces are ignored in = / != so a style id (``Heading1``) matches its name (``Heading 1``).
        actual = str(descriptor.get(attr, "") if descriptor.get(attr) is not None else "").lower()
        wanted = expected.lower()
        if op != "~=":
            actual, wanted = actual.replace(" ", ""), wanted.replace(" ", "")
        if op == "=" and actual != wanted:
            return False
        if op == "!=" and actual == wanted:
            return False
        if op == "~=" and wanted not in actual:
            return False
    if selector.contains and selector.contains.lower() not in str(descriptor.get("text") or "").lower():
        return False
    return True


# --- property values ---------------------------------------------------------------------------------------

EMU_PER_INCH = 914400
EMU_PER_CM = 360000
EMU_PER_PT = 12700
EMU_PER_PX = 9525

_LENGTH = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(cm|mm|in|pt|px|emu)?\s*$", re.IGNORECASE)


def length_emu(value: Any, *, default_unit: str = "emu") -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number, unit = float(value), default_unit
    else:
        match = _LENGTH.match(str(value or ""))
        if not match:
            raise OfficeEngineError(INVALID_REQUEST, "invalid length")
        number, unit = float(match.group(1)), (match.group(2) or default_unit).lower()
    factor = {"cm": EMU_PER_CM, "mm": EMU_PER_CM / 10, "in": EMU_PER_INCH, "pt": EMU_PER_PT, "px": EMU_PER_PX}
    return int(round(number * factor.get(unit, 1)))


def points(value: Any) -> float:
    text = str(value).strip().lower().removesuffix("pt").strip()
    try:
        return float(text)
    except ValueError as exc:
        raise OfficeEngineError(INVALID_REQUEST, "invalid font size") from exc


def flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def hex_color(value: Any) -> str:
    text = str(value or "").strip().lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", text):
        raise OfficeEngineError(INVALID_REQUEST, "colors are 6-digit hex values")
    return text


def text_window(lines: list[Any], *, start: int | None, end: int | None, max_lines: int | None) -> list[Any]:
    first = max(1, int(start)) if start else 1
    last = int(end) if end else len(lines)
    window = lines[first - 1 : last]
    if max_lines:
        window = window[: max(0, int(max_lines))]
    return window


__all__ = [
    "DOCUMENT_UNREADABLE",
    "ELEMENT_NOT_FOUND",
    "EMU_PER_CM",
    "EMU_PER_INCH",
    "EMU_PER_PT",
    "FILE_NOT_FOUND",
    "INVALID_REQUEST",
    "UNSUPPORTED_ELEMENT",
    "OfficeEngineError",
    "Segment",
    "Selector",
    "flag",
    "hex_color",
    "length_emu",
    "parse_path",
    "parse_selector",
    "points",
    "selector_matches",
    "text_window",
]
