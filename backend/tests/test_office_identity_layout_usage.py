"""S7 — layout usage learned from a template's own sample slides.

The asset-free cases run against the python-pptx default template, which ships
no sample slides at all and is therefore the proof that "no evidence" stays
``None`` instead of becoming a zeroed record. The corporate cases read the
synthetic "library" template from ``tests.office_template_fixture``, whose
eighteen sample slides (spread over two masters that repeat layout names) are
the kind of evidence this feature exists for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.office_identity.layout_usage import USAGE_SOURCE
from app.services.office_identity.layout_usage_fit import pick_layout_by_usage, usage_text_volume
from app.services.office_identity.template_snapshot import (
    SNAPSHOT_VERSION,
    build_template_snapshot,
)
from tests.office_template_fixture import write_template


@pytest.fixture(scope="module")
def default_snapshot(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The python-pptx default template — a real package with zero slides."""
    from pptx import Presentation

    path = tmp_path_factory.mktemp("default") / "default.pptx"
    Presentation().save(str(path))
    return build_template_snapshot(path)


@pytest.fixture(scope="module")
def library_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_template(tmp_path_factory.mktemp("library") / "library.potx", "library")


@pytest.fixture(scope="module")
def corp_snapshot(library_template: Path) -> dict[str, Any]:
    return build_template_snapshot(library_template)


@pytest.fixture(scope="module")
def brand_snapshot(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return build_template_snapshot(
        write_template(tmp_path_factory.mktemp("brand") / "brand.potx", "brand")
    )


# ---------------------------------------------------------------------------
# the asset-free contract
# ---------------------------------------------------------------------------


def test_template_without_sample_slides_records_no_usage(default_snapshot):
    assert default_snapshot["version"] == SNAPSHOT_VERSION
    assert default_snapshot["usage_source"] == USAGE_SOURCE
    assert default_snapshot["sample_slides"] == 0
    assert default_snapshot["summary"]["layouts_with_usage"] == 0
    # every layout carries the field, and every one of them says "no evidence"
    assert default_snapshot["layouts"]
    for layout in default_snapshot["layouts"]:
        assert "usage" in layout
        assert layout["usage"] is None


def test_usage_volume_of_an_unused_layout_is_none():
    assert usage_text_volume(None) is None
    assert usage_text_volume({"slots": []}) is None
    assert usage_text_volume({"slots": [{"lines": {"median": 2}, "chars": {"median": 40}}]}) == (2, 40)


# ---------------------------------------------------------------------------
# what the corporate template demonstrates
# ---------------------------------------------------------------------------


def test_corporate_sample_slides_teach_six_layout_names(corp_snapshot):
    """18 sample slides, spread over the layouts the author really uses."""
    used = [layout for layout in corp_snapshot["layouts"] if layout.get("usage")]
    assert corp_snapshot["sample_slides"] == 18
    assert len(used) == corp_snapshot["summary"]["layouts_with_usage"] == 7
    # 7 layout *parts*, but the template repeats names across its two masters
    assert len({layout["name"] for layout in used}) == 6

    # every sample slide is accounted for exactly once
    assert sum(layout["usage"]["sample_count"] for layout in used) == 18

    # the author's clear favourite, and it is used as a heading-only slide
    title_only = next(layout for layout in used if layout["key"] == "title-only")
    usage = title_only["usage"]
    assert usage["usage_source"] == USAGE_SOURCE
    assert usage["sample_count"] == 8
    assert usage["filled_slots"] == {"median": 1, "max": 1}
    title_slot = next(slot for slot in usage["slots"] if slot["role"] == "title")
    # one sample slide leaves its title empty
    assert title_slot["used_in"] == 7
    assert title_slot["text_style"] == "prose"
    assert 1 <= title_slot["chars"]["median"] <= 60
    assert title_slot["lines"]["median"] == 1


def test_usage_numbers_stay_plausible(corp_snapshot):
    for layout in corp_snapshot["layouts"]:
        usage = layout.get("usage")
        if not usage:
            continue
        assert usage["sample_count"] >= 1
        assert usage["filled_slots"]["median"] <= usage["filled_slots"]["max"]
        declared = {int(slot["idx"]) for slot in layout["slots"] + layout["chrome_slots"]}
        for slot in usage["slots"]:
            # usage only ever describes slots the layout itself declares
            assert slot["idx"] in declared
            assert 1 <= slot["used_in"] <= usage["sample_count"]
            assert slot["chars"]["median"] <= slot["chars"]["max"]
            assert slot["lines"]["median"] <= slot["lines"]["max"]
            assert slot["lines"]["max"] >= 1
            assert slot["text_style"] in {"prose", "bullets", "mixed"}


def test_bullet_usage_is_recognised_as_such(corp_snapshot):
    """The agenda layout's body slot is demonstrably a bullet list."""
    agenda = next(
        layout for layout in corp_snapshot["layouts"] if layout["key"] == "table-of-content"
    )
    body = next(slot for slot in agenda["usage"]["slots"] if slot["role"] == "content")
    assert body["text_style"] == "bullets"
    assert body["lines"]["median"] >= 2


def test_usage_is_deterministic(library_template, corp_snapshot):
    again = build_template_snapshot(library_template)
    assert [layout.get("usage") for layout in again["layouts"]] == [
        layout.get("usage") for layout in corp_snapshot["layouts"]
    ]


def test_brand_records_usage_only_for_its_two_sample_slides(brand_snapshot):
    assert brand_snapshot["sample_slides"] == 2
    assert brand_snapshot["summary"]["layouts_with_usage"] == 2
    title = next(layout for layout in brand_snapshot["layouts"] if layout["key"] == "title-slide")
    assert title["usage"]["sample_count"] == 1
    assert title["usage"]["filled_slots"]["max"] == 3


# ---------------------------------------------------------------------------
# using what was learned
# ---------------------------------------------------------------------------


def _layout(key: str, order: int, usage: dict[str, Any] | None) -> dict[str, Any]:
    return {"key": key, "order": order, "usage": usage}


def _usage(lines: int, chars: int) -> dict[str, Any]:
    return {"slots": [{"lines": {"median": lines}, "chars": {"median": chars}}]}


def test_usage_picks_the_layout_whose_demonstrated_volume_fits():
    short = _layout("short", 1, _usage(1, 20))
    long = _layout("long", 2, _usage(8, 300))
    assert pick_layout_by_usage([short, long], lines=8, chars=290) is long
    assert pick_layout_by_usage([short, long], lines=1, chars=25) is short


def test_a_layout_without_evidence_never_beats_one_with_it():
    demonstrated = _layout("demonstrated", 5, _usage(6, 200))
    unused = _layout("unused", 1, None)
    # even though the unused layout comes first in template order
    assert pick_layout_by_usage([unused, demonstrated], lines=1, chars=10) is demonstrated


def test_without_any_evidence_the_choice_is_left_to_the_composer():
    layouts = [_layout("a", 1, None), _layout("b", 2, None)]
    assert pick_layout_by_usage(layouts, lines=3, chars=90) is None
    assert pick_layout_by_usage([], lines=1, chars=1) is None


def test_equal_distance_falls_back_to_template_order():
    first = _layout("first", 1, _usage(2, 100))
    second = _layout("second", 2, _usage(2, 100))
    assert pick_layout_by_usage([second, first], lines=2, chars=100) is first
