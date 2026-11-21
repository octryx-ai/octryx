"""Photo and diagram image roles keep the template bleed or apply the gutter, and unknown roles fail explicitly."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.office_identity import ComposerError, build_presentation_from_plan
from app.services.office_identity.picture_safe_area import safe_picture_rect, template_margin_emu
from app.services.office_identity.template_snapshot import layout_by_key
from tests.office_identity_slide_gate_support import brand_snapshot, brand_template, diagram_png  # noqa: F401

# ---------------------------------------------------------------------------
# S3c — image_role: the picture's own nature decides the bleed
# ---------------------------------------------------------------------------


def _placed_picture(output: Path):
    from pptx import Presentation

    slide = list(Presentation(str(output)).slides)[0]
    pictures = [shape for shape in slide.shapes if shape._element.tag.endswith("}pic")]
    assert len(pictures) == 1
    return pictures[0]


ROLE_PLAN_BASE = {
    "title": "AWS Platform Topology",
    "bullets": ["11 module directories", "200 blocks"],
}


@pytest.mark.parametrize("entry_extra", [{}, {"image_role": "photo"}])
def test_photo_role_keeps_the_template_bleed(
    brand_template, brand_snapshot, tmp_path, diagram_png, entry_extra  # noqa: F811
):
    """A photo brings its own border: the slot runs to the slide edge on
    purpose, and an absent ``image_role`` must not change that silently."""
    plan = [{**ROLE_PLAN_BASE, "image_slots": [str(diagram_png)], **entry_extra}]
    output = tmp_path / "photo.pptx"
    result = build_presentation_from_plan(brand_template, brand_snapshot, plan, output)

    assert result["filled_slots"] == ["title@idx0", "body@idx1", "picture@idx12"]

    picture = _placed_picture(output)
    slide_width = brand_snapshot["slide_size"]["width_emu"]
    # the template slot ends on the slide edge, and so does the picture
    assert slide_width - (picture.left + picture.width) <= 1


def test_diagram_role_applies_the_template_gutter(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    plan = [{**ROLE_PLAN_BASE, "image_slots": [str(diagram_png)], "image_role": "diagram"}]
    output = tmp_path / "diagram.pptx"
    result = build_presentation_from_plan(brand_template, brand_snapshot, plan, output)

    assert result["filled_slots"] == ["title@idx0", "body@idx1", "picture@idx12(gutter)"]

    margin = template_margin_emu(brand_snapshot["layouts"])
    layout = layout_by_key(brand_snapshot, "content-left-image-right")
    slot = [item for item in layout["slots"] if item["role"] == "picture"][0]
    picture = _placed_picture(output)
    slide_width = brand_snapshot["slide_size"]["width_emu"]

    # nothing is glued to the slide edge
    assert slide_width - (picture.left + picture.width) >= margin
    assert picture.left >= slot["x_emu"] + margin
    assert picture.top >= slot["y_emu"] + margin
    # and the diagram is still complete and undistorted
    assert picture.width / picture.height == pytest.approx(800 / 450, rel=1e-2)
    assert picture.crop_left == 0 and picture.crop_right == 0


def test_diagram_role_does_not_double_apply_inside_the_safe_area(
    brand_template, brand_snapshot, tmp_path, diagram_png  # noqa: F811
):
    """Brand protection wins: on a full-bleed slot the safe area already
    carries the gutter, so the role must not shrink the picture twice."""
    plan = [
        {
            "layout_key": "picture-full-screen-titlebar",
            "title": "AWS Platform Topology",
            "image_slots": [str(diagram_png)],
            "image_role": "diagram",
        }
    ]
    output = tmp_path / "inset-diagram.pptx"
    result = build_presentation_from_plan(brand_template, brand_snapshot, plan, output)

    assert result["filled_slots"] == ["title@idx0", "picture@idx13(inset)"]

    layout = layout_by_key(brand_snapshot, "picture-full-screen-titlebar")
    slot = [item for item in layout["slots"] if item["role"] == "picture"][0]
    margin = template_margin_emu(brand_snapshot["layouts"])
    safe = safe_picture_rect(layout, slot, margin, set())
    picture = _placed_picture(output)

    assert picture.top >= safe["y_emu"]
    assert picture.top + picture.height <= safe["y_emu"] + safe["h_emu"]


def test_unknown_image_role_fails_explicitly(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    plan = [{**ROLE_PLAN_BASE, "image_slots": [str(diagram_png)], "image_role": "sketch"}]
    with pytest.raises(ComposerError) as excinfo:
        build_presentation_from_plan(brand_template, brand_snapshot, plan, tmp_path / "bad.pptx")

    message = str(excinfo.value)
    assert "sketch" in message
    assert "diagram" in message and "photo" in message


def test_image_role_is_deterministic(brand_template, brand_snapshot, tmp_path, diagram_png):  # noqa: F811
    plan = [{**ROLE_PLAN_BASE, "image_slots": [str(diagram_png)], "image_role": "diagram"}]
    first = build_presentation_from_plan(brand_template, brand_snapshot, plan, tmp_path / "d1.pptx")
    second = build_presentation_from_plan(brand_template, brand_snapshot, plan, tmp_path / "d2.pptx")

    assert first["filled_slots"] == second["filled_slots"]
    assert first["layout_keys"] == second["layout_keys"]
    assert first["quality_findings"] == second["quality_findings"]

    one, two = _placed_picture(tmp_path / "d1.pptx"), _placed_picture(tmp_path / "d2.pptx")
    assert (one.left, one.top, one.width, one.height) == (two.left, two.top, two.width, two.height)
