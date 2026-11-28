"""Evidence primitives for the deterministic AWS deck planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Longer enumerations are unreadable in a branded body slot; the planner shortens lists, never sentences.
MAX_LIST_ITEMS = 6

#: How many bullets fit one content slot before the planner spills over.
MAX_BULLETS_PER_SLIDE = 6


@dataclass(frozen=True)
class Bullet:
    text: str
    source: str
    #: Stable handle for a bullet the deck may move to a stronger slide; empty for bullets that never move.
    key: str = ""

    def note_line(self) -> str:
        # ``|`` separates claim from source, so the mapping stays machine
        # readable; a pipe inside the claim would break that and is folded.
        return f"- {self.text.replace('|', '/')} | Source: {self.source}"


def decision(text: str) -> str:
    return f"[DECISION: {text}]"


def missing_source(text: str) -> str:
    return f"[SOURCE MISSING: {text}]"


def check_number(text: str) -> str:
    return f"[CHECK NUMBER: {text}]"


MARKER_PREFIXES = ("[DECISION:", "[SOURCE MISSING:", "[CHECK NUMBER:")


def is_marker(text: str) -> bool:
    return text.startswith(MARKER_PREFIXES)


@dataclass
class ContentBlock:
    heading: str
    bullets: list[Bullet] = field(default_factory=list)
    #: Closed topic key (``icon_slots.ICON_TOPICS``) for this column's icon; empty when it has no icon meaning.
    topic_key: str = ""


@dataclass
class SlideDraft:
    title: str
    source: str
    shape_preference: tuple[str, ...] = ()
    subtitle: str = ""
    #: Falls back to the slide source when the subtitle is derived from the same field as the slide.
    subtitle_source: str = ""
    bullets: list[Bullet] = field(default_factory=list)
    #: Columns for layouts with several equal-rank units ("Icons N Topics"); mutually exclusive with ``bullets``.
    blocks: list[ContentBlock] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    image_role: str = ""
    markers: list[str] = field(default_factory=list)
    #: Closed theme key (``THEME_TOPIC_KEYS``) so a knowledge fact of the same topic can attach; empty otherwise.
    topic_key: str = ""
    #: Title and open-points slides exist even without bullets; a content slide with no sourced bullet is dropped.
    keep_when_empty: bool = False

    def all_bullets(self) -> list[Bullet]:
        return list(self.bullets) + [
            bullet for block in self.blocks for bullet in block.bullets
        ]

    def content_units(self) -> int:
        if self.blocks:
            return len(self.blocks)
        return 1 if self.bullets else 0


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def counts(value: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, raw in sorted(mapping(value).items()):
        number = int_or_none(raw)
        if number is not None and number > 0:
            result[str(key)] = number
    return result


def join_list(items: list[str], limit: int = MAX_LIST_ITEMS) -> str:
    if len(items) <= limit:
        return ", ".join(items)
    rest = len(items) - limit
    return ", ".join(items[:limit]) + f" (+{rest} more)"


__all__ = [
    "Bullet",
    "ContentBlock",
    "MARKER_PREFIXES",
    "MAX_BULLETS_PER_SLIDE",
    "MAX_LIST_ITEMS",
    "SlideDraft",
    "check_number",
    "counts",
    "decision",
    "int_or_none",
    "is_marker",
    "join_list",
    "mapping",
    "missing_source",
    "string_list",
    "text",
]
