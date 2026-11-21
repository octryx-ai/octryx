"""Learn from a template's own sample slides *how* each layout is used.

A layout catalog states what a layout can hold. It does not state what the
template author actually does with it — and that is the missing half of the
evidence: a corporate template often ships dozens of sample slides across its
layouts, and those slides are the author's own demonstration of "this is how you use me".

This module reads that demonstration deterministically: per layout, how often it
appears, how many slots are typically filled, how long the text in each slot
role usually is (characters and lines, median and max), whether the slot is used
as a bullet list or as a single line, and whether pictures are placed.

Nothing here guesses. A layout without a sample slide gets no usage record at
all (``usage: null`` in the snapshot) rather than an invented one.
"""

from __future__ import annotations

import statistics
from typing import Any

from .package import PresentationPackage
from .sample_slide_reading import (
    filled_placeholders,
    layout_name,
    layout_part_of_slide,
    normalized_layout_name,
    picture_count,
)

#: Where a usage record comes from. ``sample_slides`` — the template's own
#: sample slides. ``example_deck`` — a separate example presentation uploaded
#: alongside the brand template, matched to its layouts by layout name. The
#: field exists so the two sources can never be mistaken for one another.
USAGE_SOURCE = "sample_slides"
USAGE_SOURCE_EXAMPLE = "example_deck"

#: Sample slides are template evidence, not user content — but the brief stays
#: bounded regardless of how many slides a template ships.
MAX_SAMPLE_SLIDES = 400

#: Usage is recorded per slot; a layout with more slots than this is truncated
#: by ``idx`` order, which is the template's own addressing scheme.
MAX_USAGE_SLOTS = 30

#: A slot filled with at least this many non-empty paragraphs is being used as a
#: bullet list; a single paragraph is a headline or a run of prose.
BULLET_PARAGRAPH_MIN = 2

#: Chrome (footer, date, slide number) is printed by the master and says nothing
#: about how an author fills a layout.
_IGNORED_ROLES = frozenset({"chrome"})

# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def _spread(values: list[int]) -> dict[str, int]:
    """Median (lower, so the result is always an observed integer) and max."""
    if not values:
        return {"median": 0, "max": 0}
    return {"median": int(statistics.median_low(values)), "max": max(values)}


def _text_style(single: int, multi: int) -> str:
    if single and multi:
        return "mixed"
    if multi:
        return "bullets"
    if single:
        return "prose"
    return "empty"


def _slot_roles(layout: dict[str, Any]) -> dict[int, str]:
    roles: dict[int, str] = {}
    for slot in list(layout.get("slots") or ()) + list(layout.get("chrome_slots") or ()):
        index = slot.get("idx")
        if isinstance(index, int):
            roles[index] = str(slot.get("role") or "content")
    return roles


class _SlotTally:
    """Running measurements for one placeholder across all its sample slides."""

    def __init__(self, idx: int, role: str) -> None:
        self.idx = idx
        self.role = role
        self.used_in = 0
        self.chars: list[int] = []
        self.lines: list[int] = []
        self.single_paragraph = 0
        self.multi_paragraph = 0

    def add(self, paragraphs: list[str]) -> None:
        self.used_in += 1
        self.chars.append(sum(len(text) for text in paragraphs))
        self.lines.append(len(paragraphs))
        if len(paragraphs) >= BULLET_PARAGRAPH_MIN:
            self.multi_paragraph += 1
        else:
            self.single_paragraph += 1

    def record(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "role": self.role,
            "used_in": self.used_in,
            "chars": _spread(self.chars),
            "lines": _spread(self.lines),
            "bullet_samples": self.multi_paragraph,
            "text_style": _text_style(self.single_paragraph, self.multi_paragraph),
        }


class _LayoutTally:
    def __init__(self, layout: dict[str, Any], *, source: str = USAGE_SOURCE) -> None:
        self.roles = _slot_roles(layout)
        self.source = source
        self.sample_count = 0
        self.filled_counts: list[int] = []
        self.picture_counts: list[int] = []
        self.slots: dict[int, _SlotTally] = {}

    def add(self, filled: dict[int, list[str]], pictures: int) -> None:
        self.sample_count += 1
        used = 0
        for index, paragraphs in sorted(filled.items()):
            # Slides may carry placeholders the layout never declares — editors
            # write ``idx="4294967295"`` for those. Usage describes the
            # catalog's slots, so an undeclared one is not counted at all.
            role = self.roles.get(index)
            if role is None or role in _IGNORED_ROLES or not paragraphs:
                continue
            used += 1
            tally = self.slots.get(index)
            if tally is None:
                tally = self.slots[index] = _SlotTally(index, role)
            tally.add(paragraphs)
        self.filled_counts.append(used)
        self.picture_counts.append(pictures)

    def record(self) -> dict[str, Any]:
        ordered = sorted(self.slots.values(), key=lambda tally: (tally.idx, tally.role))
        return {
            "usage_source": self.source,
            "sample_count": self.sample_count,
            "filled_slots": _spread(self.filled_counts),
            "pictures": {
                "samples_with_pictures": sum(1 for count in self.picture_counts if count),
                **_spread(self.picture_counts),
            },
            "slots": [tally.record() for tally in ordered[:MAX_USAGE_SLOTS]],
        }


def collect_layout_usage(
    package: PresentationPackage, layouts: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Layout part name -> usage record, learned from the package's own slides.

    Layouts that no sample slide uses are simply absent from the result; the
    caller records ``None`` for them rather than a zeroed record, because "no
    evidence" and "evidence of zero" are different statements.
    """
    by_part = {str(layout.get("part")): layout for layout in layouts}
    tallies: dict[str, _LayoutTally] = {}
    for slide_part in package.slide_parts()[:MAX_SAMPLE_SLIDES]:
        layout_part = layout_part_of_slide(package, slide_part)
        layout = by_part.get(layout_part or "")
        if layout is None:
            continue
        root = package.xml(slide_part)
        if root is None:
            continue
        tally = tallies.get(layout_part or "")
        if tally is None:
            tally = tallies[layout_part or ""] = _LayoutTally(layout)
        tally.add(filled_placeholders(root), picture_count(root))
    return {part: tally.record() for part, tally in sorted(tallies.items())}


def collect_layout_usage_from_example(
    example_package: PresentationPackage, brand_layouts: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Learn usage from a SEPARATE example deck, keyed by the brand layout part.

    The example is a real presentation built on the same brand system; its
    slides demonstrate how each *named* layout is filled. Because it is a
    different package, a slide addresses the example's own layout parts — so it
    is matched to a brand layout by the layout's human name (``cSld/@name``),
    normalised, rather than by part path. A slide whose layout name has no brand
    counterpart contributes nothing: the example never invents a mapping, and a
    brand layout the example never demonstrates keeps no example usage.

    The returned records are keyed by the *brand* layout part and carry
    ``usage_source = example_deck``, so they drop into the snapshot's existing
    ``usage`` machinery unchanged while staying distinguishable from the
    template's own sample-slide evidence.
    """
    by_name: dict[str, dict[str, Any]] = {}
    for layout in brand_layouts:
        normalized = normalized_layout_name(str(layout.get("name") or ""))
        if normalized:
            by_name.setdefault(normalized, layout)
    tallies: dict[str, _LayoutTally] = {}
    for slide_part in example_package.slide_parts()[:MAX_SAMPLE_SLIDES]:
        layout_part = layout_part_of_slide(example_package, slide_part)
        if not layout_part:
            continue
        brand_layout = by_name.get(normalized_layout_name(layout_name(example_package, layout_part)))
        if brand_layout is None:
            continue
        root = example_package.xml(slide_part)
        if root is None:
            continue
        key = str(brand_layout.get("part"))
        tally = tallies.get(key)
        if tally is None:
            tally = tallies[key] = _LayoutTally(brand_layout, source=USAGE_SOURCE_EXAMPLE)
        tally.add(filled_placeholders(root), picture_count(root))
    return {part: tally.record() for part, tally in sorted(tallies.items())}


__all__ = [
    "BULLET_PARAGRAPH_MIN",
    "MAX_SAMPLE_SLIDES",
    "MAX_USAGE_SLOTS",
    "USAGE_SOURCE",
    "collect_layout_usage",
]
