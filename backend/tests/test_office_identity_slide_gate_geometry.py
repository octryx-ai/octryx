"""Coverage geometry, full-bleed flags, template margins, title-band safe areas and picture insets."""

from __future__ import annotations

import pytest

from app.services.office_identity import build_presentation_from_plan, check_deck_quality
from app.services.office_identity.picture_safe_area import safe_picture_rect, template_margin_emu
from app.services.office_identity.slot_coverage import annotate_coverage, covered_fraction
from app.services.office_identity.template_snapshot import has_full_bleed_picture, layout_by_key
from tests.office_identity_slide_gate_support import brand_snapshot, brand_template, diagram_png  # noqa: F401

SLIDE_16_9 = {"width_emu": 9144000, "height_emu": 5143500}


# ---------------------------------------------------------------------------
# coverage geometry (no assets)
# ---------------------------------------------------------------------------


def test_full_bleed_and_coverage_are_computed_from_geometry():
    slots = [
        {"idx": 0, "role": "title", "x_emu": 180000, "y_emu": 195000,
         "w_emu": 8780000, "h_emu": 576000},
        {"idx": 11, "role": "chrome", "x_emu": 180000, "y_emu": 4700000,
         "w_emu": 2000000, "h_emu": 300000},
        {"idx": 13, "role": "picture", "x_emu": 0, "y_emu": 0,
         "w_emu": 9144000, "h_emu": 5143500},
        {"idx": 12, "role": "picture", "x_emu": 4680612, "y_emu": 1131887,
         "w_emu": 4463387, "h_emu": 3563937},
    ]
    annotate_coverage(slots, SLIDE_16_9)
    by_idx = {slot["idx"]: slot for slot in slots}

    assert by_idx[13]["full_bleed"] is True
    assert by_idx[13]["slide_area_ratio"] == 1.0
    assert by_idx[13]["covers"] == [0, 11, 12]

    # the framed picture next to the title covers nothing and is not full bleed
    assert by_idx[12]["full_bleed"] is False
    assert by_idx[12]["covers"] == []
    assert by_idx[12]["slide_area_ratio"] == pytest.approx(0.3382, abs=1e-3)

    # a large *text* slot is not a branding failure
    assert by_idx[0]["full_bleed"] is False


def test_full_bleed_is_set_by_covering_the_title_even_below_the_area_threshold():
    slots = [
        {"idx": 0, "role": "title", "x_emu": 200000, "y_emu": 200000,
         "w_emu": 4000000, "h_emu": 500000},
        {"idx": 13, "role": "picture", "x_emu": 0, "y_emu": 0,
         "w_emu": 4572000, "h_emu": 2571750},
    ]
    annotate_coverage(slots, SLIDE_16_9)

    picture = slots[1]
    assert picture["slide_area_ratio"] == 0.25  # far below the 90 % area rule
    assert picture["covers"] == [0]
    assert picture["full_bleed"] is True


def test_covered_fraction_is_relative_to_the_inner_slot():
    outer = {"x_emu": 0, "y_emu": 0, "w_emu": 1000, "h_emu": 1000}
    inner = {"x_emu": 500, "y_emu": 0, "w_emu": 1000, "h_emu": 1000}
    assert covered_fraction(outer, inner) == 0.5
    assert covered_fraction(outer, {"x_emu": 2000, "y_emu": 0, "w_emu": 10, "h_emu": 10}) == 0.0
    assert covered_fraction(outer, {"x_emu": None, "y_emu": 0, "w_emu": 10, "h_emu": 10}) == 0.0


def test_full_bleed_flag_marks_the_slide_filling_picture_slots(brand_snapshot):  # noqa: F811
    statement = layout_by_key(brand_snapshot, "statement-with-picture")
    framed = layout_by_key(brand_snapshot, "content-left-image-right")

    picture = [slot for slot in statement["slots"] if slot["role"] == "picture"][0]
    assert picture["idx"] == 13
    assert picture["full_bleed"] is True
    assert picture["slide_area_ratio"] == 1.0
    assert 0 in picture["covers"]  # the title rectangle
    assert has_full_bleed_picture(statement) is True

    framed_picture = [slot for slot in framed["slots"] if slot["role"] == "picture"][0]
    assert framed_picture["full_bleed"] is False
    assert has_full_bleed_picture(framed) is False


# ---------------------------------------------------------------------------
# S3b — safe area, inset placement, title legibility
# ---------------------------------------------------------------------------


def test_template_margin_is_derived_from_the_layouts(brand_snapshot):  # noqa: F811
    """5 mm is the gutter the corporate layouts start their content at."""
    assert template_margin_emu(brand_snapshot["layouts"]) == 180000


def test_safe_area_keeps_clear_of_a_bottom_title_band(brand_snapshot):  # noqa: F811
    layout = layout_by_key(brand_snapshot, "picture-full-screen-titlebar")
    picture = [slot for slot in layout["slots"] if slot["role"] == "picture"][0]
    title = [slot for slot in layout["slots"] if slot["role"] == "title"][0]
    margin = template_margin_emu(brand_snapshot["layouts"])

    rect = safe_picture_rect(layout, picture, margin, set())

    assert rect is not None
    # the band sits at the bottom, so the safe area is the strip above it
    assert rect["y_emu"] == margin
    assert rect["y_emu"] + rect["h_emu"] == title["y_emu"] - margin
    assert rect["x_emu"] == margin
    assert rect["x_emu"] + rect["w_emu"] == brand_snapshot["slide_size"]["width_emu"] - margin


def test_safe_area_keeps_clear_of_a_top_title_band(brand_snapshot):  # noqa: F811
    layout = layout_by_key(brand_snapshot, "title-and-subtitle-picture")
    picture = [slot for slot in layout["slots"] if slot["role"] == "picture"][0]
    title = [slot for slot in layout["slots"] if slot["role"] == "title"][0]
    margin = template_margin_emu(brand_snapshot["layouts"])

    rect = safe_picture_rect(layout, picture, margin, set())

    assert rect is not None
    assert rect["y_emu"] == title["y_emu"] + title["h_emu"] + margin
    # and it stops above the chrome row rather than running to the slide edge
    assert rect["y_emu"] + rect["h_emu"] < brand_snapshot["slide_size"]["height_emu"] - margin


def test_safe_area_is_none_when_nothing_usable_remains():
    layout = {
        "slots": [
            {"idx": 0, "role": "title", "x_emu": 0, "y_emu": 0,
             "w_emu": 9144000, "h_emu": 5000000},
            {"idx": 13, "role": "picture", "x_emu": 0, "y_emu": 0,
             "w_emu": 9144000, "h_emu": 5143500},
        ],
        "chrome_slots": [],
    }
    picture = layout["slots"][1]
    assert safe_picture_rect(layout, picture, 180000, set()) is None


def test_inset_places_the_picture_inside_the_safe_area(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    from pptx import Presentation

    layout = layout_by_key(brand_snapshot, "picture-full-screen-titlebar")
    picture_slot = [slot for slot in layout["slots"] if slot["role"] == "picture"][0]
    title = [slot for slot in layout["slots"] if slot["role"] == "title"][0]
    margin = template_margin_emu(brand_snapshot["layouts"])
    safe = safe_picture_rect(layout, picture_slot, margin, set())

    output = tmp_path / "inset.pptx"
    plan = [
        {
            "layout_key": "picture-full-screen-titlebar",
            "title": "AWS Platform Topology",
            "image_slots": [str(diagram_png)],
        }
    ]
    result = build_presentation_from_plan(brand_template, brand_snapshot, plan, output)

    assert "picture@idx13(inset)" in result["filled_slots"]

    slide = list(Presentation(str(output)).slides)[0]
    pictures = [shape for shape in slide.shapes if shape._element.tag.endswith("}pic")]
    placed = pictures[0]

    # inside the safe rectangle, and therefore clear of the title band
    assert placed.left >= safe["x_emu"]
    assert placed.top >= safe["y_emu"]
    assert placed.left + placed.width <= safe["x_emu"] + safe["w_emu"]
    assert placed.top + placed.height <= title["y_emu"] - margin
    # and no longer glued to the slide edge
    assert placed.left + placed.width < brand_snapshot["slide_size"]["width_emu"] - margin
    # aspect preserved
    assert placed.width / placed.height == pytest.approx(800 / 450, rel=1e-2)


def test_inset_case_is_not_reported_as_covering_the_title(
    brand_template, brand_snapshot, tmp_path, diagram_png  # noqa: F811
):
    plan = [
        {
            "layout_key": "picture-full-screen-titlebar",
            "title": "AWS Platform Topology",
            "image_slots": [str(diagram_png)],
        }
    ]
    result = build_presentation_from_plan(
        brand_template, brand_snapshot, plan, tmp_path / "protected.pptx"
    )
    assert result["quality_findings"] == []


def test_uninset_full_bleed_picture_is_still_reported(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    """The composer now always insets, so the unprotected case is built the way
    any other tool would produce it: the picture straight on the full slot."""
    from pptx import Presentation

    plan = [
        {
            "layout_key": "statement-with-picture",
            "title": "AWS Platform Topology",
            "image_slots": [str(diagram_png)],
        }
    ]
    output = tmp_path / "unprotected.pptx"
    build_presentation_from_plan(brand_template, brand_snapshot, plan, output)

    presentation = Presentation(str(output))
    for shape in list(presentation.slides)[0].shapes:
        if shape._element.tag.endswith("}pic"):
            shape.left, shape.top = 833715, 0
            shape.width, shape.height = 7476570, 5143500
    presentation.save(str(output))

    findings = check_deck_quality(brand_snapshot, plan, output)
    covered = [f for f in findings if f["code"] == "picture_covers_title"]

    assert len(covered) == 1
    assert covered[0]["slot_idx"] == 13
    assert covered[0]["severity"] == "warning"
    assert "logo are not visible" in covered[0]["message"]
