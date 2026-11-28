"""Title backdrop evidence, title legibility and the deterministic layout preference for picture slides."""

from __future__ import annotations

from app.services.office_identity import build_presentation_from_plan
from app.services.office_identity.picture_safe_area import has_title_backdrop
from app.services.office_identity.template_snapshot import has_full_bleed_picture, layout_by_key
from tests.services.office_identity.office_identity_slide_gate_support import (  # noqa: F401
    _codes,
    brand_snapshot,
    brand_template,
    diagram_png,
)


def test_title_backdrop_evidence_separates_identical_geometry(brand_snapshot):  # noqa: F811
    plain = layout_by_key(brand_snapshot, "picture-full-screen")
    titlebar = layout_by_key(brand_snapshot, "picture-full-screen-titlebar")

    plain_picture = [slot for slot in plain["slots"] if slot["role"] == "picture"][0]
    bar_picture = [slot for slot in titlebar["slots"] if slot["role"] == "picture"][0]
    assert (plain_picture["x_emu"], plain_picture["w_emu"]) == (
        bar_picture["x_emu"], bar_picture["w_emu"]
    )

    assert has_title_backdrop(plain) is False
    assert has_title_backdrop(titlebar) is True
    # the layout-level background of this one carries the title instead
    assert has_title_backdrop(layout_by_key(brand_snapshot, "title-and-subtitle-picture")) is True


def test_title_illegible_is_reported_for_a_light_title_without_backdrop(
    brand_template, brand_snapshot, tmp_path, diagram_png  # noqa: F811
):
    plan = [
        {
            "layout_key": "picture-full-screen",
            "title": "AWS Platform Topology",
            "image_slots": [str(diagram_png)],
        }
    ]
    result = build_presentation_from_plan(
        brand_template, brand_snapshot, plan, tmp_path / "illegible.pptx"
    )
    illegible = [f for f in result["quality_findings"] if f["code"] == "title_illegible"]

    assert len(illegible) == 1
    assert illegible[0]["slot_idx"] == 0
    assert "#FFFFFF" in illegible[0]["message"]
    # the titlebar twin, same geometry, stays silent
    titlebar = dict(plan[0], layout_key="picture-full-screen-titlebar")
    other = build_presentation_from_plan(
        brand_template, brand_snapshot, [titlebar], tmp_path / "legible.pptx"
    )
    assert "title_illegible" not in _codes(other["quality_findings"])


def test_dark_title_on_the_plain_background_stays_silent(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    plan = [{"title": "AWS Platform Topology", "bullets": ["a"], "image_slots": [str(diagram_png)]}]
    result = build_presentation_from_plan(
        brand_template, brand_snapshot, plan, tmp_path / "dark-title.pptx"
    )
    assert result["layout_keys"] == ["content-left-image-right"]
    assert "title_illegible" not in _codes(result["quality_findings"])


def test_titled_diagram_slide_prefers_a_framed_picture_slot(
    brand_template, brand_snapshot, tmp_path, diagram_png  # noqa: F811
):
    plan = [{"title": "AWS Platform Topology", "image_slots": [str(diagram_png)]}]
    result = build_presentation_from_plan(
        brand_template, brand_snapshot, plan, tmp_path / "framed.pptx"
    )

    assert result["layout_keys"] == ["content-left-image-right"]
    assert result["filled_slots"] == ["title@idx0", "picture@idx12"]
    assert "picture_covers_title" not in _codes(result["quality_findings"])


def test_bullets_fill_the_content_slot_beside_the_picture(
    brand_template, brand_snapshot, tmp_path, diagram_png  # noqa: F811
):
    from pptx import Presentation

    plan = [
        {
            "title": "AWS Platform Topology",
            "bullets": ["11 module directories", "200 blocks", "Providers: aws 128"],
            "image_slots": [str(diagram_png)],
        }
    ]
    output = tmp_path / "bullets.pptx"
    result = build_presentation_from_plan(brand_template, brand_snapshot, plan, output)

    assert result["layout_keys"] == ["content-left-image-right"]
    assert result["filled_slots"] == ["title@idx0", "body@idx1", "picture@idx12"]
    assert result["quality_findings"] == []

    slide = list(Presentation(str(output)).slides)[0]
    body = {
        placeholder.placeholder_format.idx: placeholder.text_frame.text
        for placeholder in slide.placeholders
        if placeholder.has_text_frame and placeholder.text_frame.text
    }
    assert body[1] == "11 module directories\n200 blocks\nProviders: aws 128"


def test_empty_content_next_to_picture_is_reported_as_info(
    brand_template, brand_snapshot, tmp_path, diagram_png  # noqa: F811
):
    plan = [{"title": "AWS Platform Topology", "image_slots": [str(diagram_png)]}]
    result = build_presentation_from_plan(
        brand_template, brand_snapshot, plan, tmp_path / "half-empty.pptx"
    )
    empty = [
        f for f in result["quality_findings"] if f["code"] == "empty_content_next_to_picture"
    ]

    assert len(empty) == 1
    assert empty[0]["severity"] == "info"
    assert empty[0]["slot_idx"] == 1
    assert "reads as unfinished" in empty[0]["message"]


def test_untitled_picture_slide_may_still_be_full_bleed(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    plan = [{"image_slots": [str(diagram_png)]}]
    result = build_presentation_from_plan(
        brand_template, brand_snapshot, plan, tmp_path / "untitled.pptx"
    )

    assert has_full_bleed_picture(layout_by_key(brand_snapshot, result["layout_keys"][0]))
    assert "(inset)" not in " ".join(result["filled_slots"])
    assert "picture_covers_title" not in _codes(result["quality_findings"])


def test_layout_preference_is_deterministic(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    plan = [{"title": "AWS Platform Topology", "image_slots": [str(diagram_png)]}]
    first = build_presentation_from_plan(brand_template, brand_snapshot, plan, tmp_path / "a.pptx")
    second = build_presentation_from_plan(brand_template, brand_snapshot, plan, tmp_path / "b.pptx")

    assert first["layout_keys"] == second["layout_keys"]
    assert first["filled_slots"] == second["filled_slots"]
    assert first["quality_findings"] == second["quality_findings"]
