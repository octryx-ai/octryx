"""Evidence primitives for the deterministic AWS deck planner.

Every statement a deck makes has to be traceable to a field of the
``aws_topology_snapshot`` (or to a knowledge fact that carries its own source).
This module holds the smallest pieces of that contract: the bullet/source pair,
the three visible-gap markers and the snapshot readers; the closed catalog that
maps AWS node types to slide themes is ``aws_deck_themes``. It knows nothing
about layouts or slides — the planner in ``aws_deck_plan`` composes these into
plan entries.

The gap markers deliberately mirror the coverage legends of the AWS diagrams:
an admitted hole is better than invented content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: A bullet longer than this is unreadable in a branded body slot; the planner
#: shortens *lists* instead of truncating sentences, so this is a guard rail for
#: composed enumerations only.
MAX_LIST_ITEMS = 6

#: How many bullets fit one content slot before the planner spills over.
MAX_BULLETS_PER_SLIDE = 6


# ---------------------------------------------------------------------------
# bullets and markers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bullet:
    """One claim on a slide plus the evidence field it was derived from."""

    text: str
    source: str
    #: Stable handle for a bullet the deck may move to a stronger slide (a
    #: statement or an icons slide). Empty for bullets that never move.
    key: str = ""

    def note_line(self) -> str:
        # ``|`` separates claim from source, so the mapping stays machine
        # readable; a pipe inside the claim would break that and is folded.
        return f"- {self.text.replace('|', '/')} | Source: {self.source}"


def decision(text: str) -> str:
    """A human has to decide this; the planner must not."""
    return f"[DECISION: {text}]"


def missing_source(text: str) -> str:
    """Evidence for this is absent — say so instead of filling it with prose."""
    return f"[SOURCE MISSING: {text}]"


def check_number(text: str) -> str:
    """The number exists but its completeness is not guaranteed."""
    return f"[CHECK NUMBER: {text}]"


MARKER_PREFIXES = ("[DECISION:", "[SOURCE MISSING:", "[CHECK NUMBER:")


def is_marker(text: str) -> bool:
    return text.startswith(MARKER_PREFIXES)


# ---------------------------------------------------------------------------
# slide drafts
# ---------------------------------------------------------------------------


@dataclass
class ContentBlock:
    """One column of a multi-column layout: a heading and what sits under it."""

    heading: str
    bullets: list[Bullet] = field(default_factory=list)
    #: Closed topic key (see ``icon_slots.ICON_TOPICS``) naming the icon this
    #: column's holder should carry. Empty when the column has no icon meaning.
    topic_key: str = ""


@dataclass
class SlideDraft:
    """A slide before a layout is chosen for it."""

    title: str
    source: str
    shape_preference: tuple[str, ...] = ()
    subtitle: str = ""
    #: Where the subtitle came from; falls back to the slide source when the
    #: subtitle is derived from the same field as the slide itself.
    subtitle_source: str = ""
    bullets: list[Bullet] = field(default_factory=list)
    #: Columns for layouts that carry several equal-rank content units (the
    #: "Icons N Topics" family). Mutually exclusive with ``bullets``.
    blocks: list[ContentBlock] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    image_role: str = ""
    markers: list[str] = field(default_factory=list)
    #: Closed theme key (see ``THEME_TOPIC_KEYS``) for the topic this slide
    #: covers, so a knowledge fact of the same topic can be attached to it.
    #: Empty for slides that are not one of the resource themes.
    topic_key: str = ""
    #: Title slide and the open-points slide exist even without bullets; a
    #: content slide without a single sourced bullet is dropped instead of
    #: being padded.
    keep_when_empty: bool = False

    def all_bullets(self) -> list[Bullet]:
        """Every sourced claim on this slide, columns included."""
        return list(self.bullets) + [
            bullet for block in self.blocks for bullet in block.bullets
        ]

    def content_units(self) -> int:
        """How many content units a layout has to offer for this slide."""
        if self.blocks:
            return len(self.blocks)
        return 1 if self.bullets else 0


# ---------------------------------------------------------------------------
# snapshot readers (never raise on a thin snapshot)
# ---------------------------------------------------------------------------


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
    """Read a ``{name: count}`` map, dropping anything that is not countable."""
    result: dict[str, int] = {}
    for key, raw in sorted(mapping(value).items()):
        number = int_or_none(raw)
        if number is not None and number > 0:
            result[str(key)] = number
    return result


def join_list(items: list[str], limit: int = MAX_LIST_ITEMS) -> str:
    """Join a list without ever hiding that it was shortened."""
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
