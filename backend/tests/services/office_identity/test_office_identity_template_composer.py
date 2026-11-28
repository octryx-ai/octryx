"""The deck composer builds a readable, deterministic deck from the synthetic template and fails explicitly on unknown layouts, over-capacity plans and unknown content shapes."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.office_identity import ComposerError, build_presentation_from_plan
from app.services.office_identity.template_snapshot import layouts_by_shape
from tests.services.office_identity.office_identity_template_snapshot_support import (  # noqa: F401
    brand_snapshot,
    brand_template,
)

PLAN = [
    {
        "layout_key": "title-slide",
        "title": "Deterministic Office Composer",
        "subtitle": "Template evidence instead of guesswork",
    },
    {
        "content_shape": "icons_3",
        "title": "Three guarantees",
        "blocks": [
            {"heading": "Evidence", "bullets": ["Theme via master", "No hard-coded theme1"]},
            {"heading": "Capacity", "bullets": ["Layouts state what they hold"]},
            {"heading": "No invention", "bullets": ["Only template placeholders"]},
        ],
    },
    {
        "title": "Next steps",
        "bullets": ["Slide gate", "Rendering", "Enforcement"],
        "notes": "Evidence: work package 2026-07-20.",
    },
]


@pytest.fixture(scope="module")
def composed(tmp_path_factory, brand_template, brand_snapshot) -> tuple[dict, Path]:  # noqa: F811
    output = tmp_path_factory.mktemp("composer") / "deck.pptx"
    result = build_presentation_from_plan(brand_template, brand_snapshot, PLAN, output)
    return result, output


def _write_png(path: Path, *, width: int, height: int) -> Path:
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes([0x40, 0x00, 0x66] * width) for _ in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def test_composer_builds_a_readable_deck(composed):
    from pptx import Presentation

    result, output = composed
    assert output.is_file()
    assert result["slide_count"] == 3

    presentation = Presentation(str(output))
    assert len(presentation.slides._sldIdLst) == 3


def test_composer_removes_the_template_sample_slides(composed, brand_snapshot):  # noqa: F811
    result, _output = composed
    assert result["removed_sample_slides"] == brand_snapshot["sample_slides"]
    assert result["removed_sample_slides"] > 0


def test_composer_fills_placeholders_by_idx(composed):
    from pptx import Presentation

    _result, output = composed
    slides = list(Presentation(str(output)).slides)

    assert slides[0].slide_layout.name == "Title Slide"
    assert slides[1].slide_layout.name == "Icons 3 Topics"

    title_texts = {}
    for slide in slides:
        for placeholder in slide.placeholders:
            if placeholder.has_text_frame and placeholder.text_frame.text:
                title_texts.setdefault(slide.slide_layout.name, {})[
                    placeholder.placeholder_format.idx
                ] = placeholder.text_frame.text

    assert title_texts["Title Slide"][0] == "Deterministic Office Composer"
    assert title_texts["Title Slide"][1] == "Template evidence instead of guesswork"
    icons = title_texts["Icons 3 Topics"]
    assert icons[0] == "Three guarantees"
    assert icons[16] == "Evidence"
    assert icons[17] == "Theme via master\nNo hard-coded theme1"
    assert icons[20] == "No invention"


def test_composer_writes_speaker_notes(composed):
    from pptx import Presentation

    _result, output = composed
    slides = list(Presentation(str(output)).slides)

    assert slides[2].notes_slide.notes_text_frame.text == "Evidence: work package 2026-07-20."
    assert not slides[0].notes_slide.notes_text_frame.text.strip()


def test_composer_is_deterministic(tmp_path, brand_template, brand_snapshot):  # noqa: F811
    first = build_presentation_from_plan(brand_template, brand_snapshot, PLAN, tmp_path / "a.pptx")
    second = build_presentation_from_plan(brand_template, brand_snapshot, PLAN, tmp_path / "b.pptx")
    assert first["layout_keys"] == second["layout_keys"]
    assert first["filled_slots"] == second["filled_slots"]
    assert first["layout_keys"][0] == "title-slide"
    assert first["layout_keys"][1] == "icons-3-topics"


def test_composer_fits_images_without_distortion(tmp_path, brand_template, brand_snapshot):  # noqa: F811
    from pptx import Presentation

    image = _write_png(tmp_path / "diagram.png", width=400, height=100)
    layout = layouts_by_shape(brand_snapshot, "image_grid_3")[0]
    picture_slot = [slot for slot in layout["slots"] if slot["role"] == "picture"][0]

    output = tmp_path / "images.pptx"
    plan = [{"layout_key": layout["key"], "title": "Architecture", "image_slots": [str(image)]}]
    result = build_presentation_from_plan(brand_template, brand_snapshot, plan, output)

    assert f"picture@idx{picture_slot['idx']}" in result["filled_slots"]

    slide = list(Presentation(str(output)).slides)[0]
    pictures = [shape for shape in slide.shapes if shape._element.tag.endswith("}pic")]
    assert len(pictures) == 1
    picture = pictures[0]
    assert picture.width / picture.height == pytest.approx(4.0, rel=1e-2)
    assert picture.width <= picture_slot["w_emu"]
    assert picture.height <= picture_slot["h_emu"]
    assert picture.crop_left == 0 and picture.crop_top == 0


def test_unknown_layout_key_lists_available_keys(tmp_path, brand_template, brand_snapshot):  # noqa: F811
    with pytest.raises(ComposerError) as excinfo:
        build_presentation_from_plan(
            brand_template, brand_snapshot, [{"layout_key": "does-not-exist", "title": "x"}],
            tmp_path / "fail.pptx",
        )
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "Available layout keys" in message
    assert "title-slide" in message


def test_over_capacity_plan_fails_explicitly(tmp_path, brand_template, brand_snapshot):  # noqa: F811
    blocks = [{"heading": f"H{index}", "bullets": ["x"]} for index in range(12)]
    with pytest.raises(ComposerError) as excinfo:
        build_presentation_from_plan(
            brand_template, brand_snapshot, [{"title": "too much", "blocks": blocks}],
            tmp_path / "fail.pptx",
        )
    assert "no layout in this template can hold" in str(excinfo.value)


def test_unknown_content_shape_fails_explicitly(tmp_path, brand_template, brand_snapshot):  # noqa: F811
    with pytest.raises(ComposerError) as excinfo:
        build_presentation_from_plan(
            brand_template, brand_snapshot, [{"content_shape": "carousel", "title": "x"}],
            tmp_path / "fail.pptx",
        )
    assert "Available shapes" in str(excinfo.value)
