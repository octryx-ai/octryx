"""Slide-gate tests (S3) — one per finding class, plus the layout preference.

Most cases run against python-pptx's own default template, which is written to
a temporary file and snapshotted like any other template: the gate is then
provable without corporate assets. The full-bleed behaviour that motivated the
slice is corporate-template specific and stays behind the same fixture-constant
skip as the S1/S2 tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.office_identity import build_presentation_from_plan, check_deck_quality
from app.services.office_identity.template_snapshot import build_template_snapshot
from tests.office_identity_slide_gate_support import _codes, _write_png


@pytest.fixture(scope="module")
def default_template(tmp_path_factory) -> Path:
    from pptx import Presentation

    path = tmp_path_factory.mktemp("default-template") / "default.pptx"
    Presentation().save(str(path))
    return path


@pytest.fixture(scope="module")
def default_snapshot(default_template) -> dict[str, Any]:
    return build_template_snapshot(default_template)


# ---------------------------------------------------------------------------
# the negative case: a clean deck reports nothing
# ---------------------------------------------------------------------------


CLEAN_PLAN = [
    {"layout_key": "title-slide", "title": "Quality gate", "subtitle": "Measured, not assumed"},
    {"layout_key": "title-and-content", "title": "Findings", "bullets": ["One", "Two", "Three"]},
]


@pytest.fixture()
def clean_deck(tmp_path, default_template, default_snapshot) -> dict[str, Any]:
    return build_presentation_from_plan(
        default_template, default_snapshot, CLEAN_PLAN, tmp_path / "clean.pptx"
    )


def test_clean_deck_produces_no_findings(clean_deck):
    assert clean_deck["quality_findings"] == []


def test_composer_returns_the_findings_in_its_result(clean_deck):
    assert "quality_findings" in clean_deck


def test_gate_is_deterministic(clean_deck, default_snapshot, tmp_path, default_template):
    noisy = [{"layout_key": "title-and-content", "bullets": ["x" * 400] * 12}]
    result = build_presentation_from_plan(
        default_template, default_snapshot, noisy, tmp_path / "noisy.pptx"
    )
    again = check_deck_quality(default_snapshot, noisy, result["output_path"])

    assert result["quality_findings"] == again
    assert result["quality_findings"], "the noisy deck must produce findings at all"
    assert again == sorted(
        again,
        key=lambda item: (
            item["slide_index"],
            item["code"],
            item["slot_idx"] if item["slot_idx"] is not None else -1,
            item["message"],
        ),
    )


def test_every_finding_carries_its_location(default_snapshot, tmp_path, default_template):
    plan = [{"layout_key": "title-and-content", "bullets": ["y" * 300] * 10}]
    result = build_presentation_from_plan(
        default_template, default_snapshot, plan, tmp_path / "located.pptx"
    )
    for finding in result["quality_findings"]:
        assert finding["slide_index"] == 1
        assert finding["layout_key"] == "title-and-content"
        assert isinstance(finding["message"], str) and finding["message"]
        assert finding["slot_idx"] is None or isinstance(finding["slot_idx"], int)
        assert finding["severity"] in {"info", "warning"}


# ---------------------------------------------------------------------------
# one test per finding class
# ---------------------------------------------------------------------------


def test_text_overflow_is_reported(default_snapshot, tmp_path, default_template):
    plan = [{"layout_key": "title-and-content", "title": "Too much",
             "bullets": ["A rather long sentence about the platform." * 3] * 12}]
    result = build_presentation_from_plan(
        default_template, default_snapshot, plan, tmp_path / "overflow.pptx"
    )
    overflow = [f for f in result["quality_findings"] if f["code"] == "text_overflow"]

    assert overflow, _codes(result["quality_findings"])
    assert overflow[0]["slot_idx"] == 1
    assert "line(s)" in overflow[0]["message"]


def test_text_overflow_stays_silent_for_text_that_fits(clean_deck):
    assert "text_overflow" not in _codes(clean_deck["quality_findings"])


def test_empty_required_slot_is_reported(default_snapshot, tmp_path, default_template):
    plan = [{"layout_key": "title-and-content", "bullets": ["Only body text, no title"]}]
    result = build_presentation_from_plan(
        default_template, default_snapshot, plan, tmp_path / "empty-title.pptx"
    )
    empty = [f for f in result["quality_findings"] if f["code"] == "empty_required_slot"]

    assert [finding["slot_idx"] for finding in empty] == [0]
    assert "title slot idx0" in empty[0]["message"]


def test_empty_content_area_is_reported(default_snapshot, tmp_path, default_template):
    plan = [{"layout_key": "title-and-content", "title": "Heading only"}]
    result = build_presentation_from_plan(
        default_template, default_snapshot, plan, tmp_path / "empty-body.pptx"
    )
    empty = [f for f in result["quality_findings"] if f["code"] == "empty_required_slot"]

    assert empty and empty[0]["slot_idx"] is None
    assert "content slot" in empty[0]["message"]


def test_capacity_exceeded_is_reported(default_snapshot, tmp_path, default_template):
    """The composer refuses an over-capacity plan, so the gate is checked
    directly against a deck/plan pair that disagree."""
    built = build_presentation_from_plan(
        default_template, default_snapshot,
        [{"layout_key": "title-and-content", "title": "One block", "bullets": ["a"]}],
        tmp_path / "capacity.pptx",
    )
    inflated = [
        {
            "layout_key": "title-and-content",
            "title": "One block",
            "blocks": [{"heading": f"H{index}", "bullets": ["a"]} for index in range(5)],
            "image_slots": [],
        }
    ]
    findings = check_deck_quality(default_snapshot, inflated, built["output_path"])
    capacity = [f for f in findings if f["code"] == "capacity_exceeded"]

    assert capacity, _codes(findings)
    assert "needs 5 content unit(s)" in capacity[0]["message"]
    assert "holds 1" in capacity[0]["message"]


def test_image_distorted_is_reported(default_snapshot, tmp_path, default_template):
    from pptx import Presentation

    image = _write_png(tmp_path / "wide.png", width=400, height=100)
    plan = [{"layout_key": "picture-with-caption", "title": "Diagram",
             "bullets": ["Source: snapshot"], "image_slots": [str(image)]}]
    output = tmp_path / "distorted.pptx"
    result = build_presentation_from_plan(default_template, default_snapshot, plan, output)
    assert "image_distorted" not in _codes(result["quality_findings"])

    # squash the picture: the composer never does this, a hand edit can
    presentation = Presentation(str(output))
    for shape in list(presentation.slides)[0].shapes:
        if shape._element.tag.endswith("}pic"):
            shape.width = int(shape.width * 0.5)
    presentation.save(str(output))

    findings = check_deck_quality(default_snapshot, plan, output)
    distorted = [f for f in findings if f["code"] == "image_distorted"]

    assert distorted, _codes(findings)
    assert "distortion" in distorted[0]["message"]


def test_off_brand_font_or_color_is_reported(default_snapshot, tmp_path, default_template):
    from pptx import Presentation
    from pptx.dml.color import RGBColor

    output = tmp_path / "off-brand.pptx"
    build_presentation_from_plan(default_template, default_snapshot, CLEAN_PLAN, output)

    presentation = Presentation(str(output))
    run = list(presentation.slides)[1].placeholders[0].text_frame.paragraphs[0].runs[0]
    run.font.name = "Comic Sans MS"
    run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
    presentation.save(str(output))

    findings = check_deck_quality(default_snapshot, CLEAN_PLAN, output)
    off_brand = [f for f in findings if f["code"] == "off_brand_font_or_color"]

    assert len(off_brand) == 2
    assert off_brand[0]["slide_index"] == 2
    messages = " ".join(finding["message"] for finding in off_brand)
    assert "Comic Sans MS" in messages
    assert "#FF0000" in messages


def test_theme_font_and_theme_colour_stay_silent(default_snapshot, tmp_path, default_template):
    from pptx import Presentation

    output = tmp_path / "on-brand.pptx"
    build_presentation_from_plan(default_template, default_snapshot, CLEAN_PLAN, output)

    presentation = Presentation(str(output))
    run = list(presentation.slides)[1].placeholders[0].text_frame.paragraphs[0].runs[0]
    run.font.name = default_snapshot["theme"]["fonts"]["major"]
    presentation.save(str(output))

    findings = check_deck_quality(default_snapshot, CLEAN_PLAN, output)
    assert "off_brand_font_or_color" not in _codes(findings)


def test_unknown_layout_is_reported(default_snapshot, clean_deck):
    stripped = {**default_snapshot, "layouts": []}
    findings = check_deck_quality(stripped, CLEAN_PLAN, clean_deck["output_path"])

    assert _codes(findings) == ["unknown_layout", "unknown_layout"]
    assert "not in the snapshot" in findings[0]["message"]
