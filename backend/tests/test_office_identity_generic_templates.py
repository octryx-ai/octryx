"""Deck planning works on any template, detected by structure — not on one template's names.

Every case runs on three templates (see ``tests.office_generic_templates_support``):
the synthetic corporate template, python-pptx's default template and a template
whose layouts are only called "Layout 1…n". The AWS deck plan, the generic deck
plan and normalisation must keep the title slide on a title layout with title
and subtitle, use a section layout for dividers where one exists, and put the
three equal-rank figures on a three-column layout where one exists.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from app.services.office_identity import build_generic_deck_plan
from app.services.office_identity.aws_deck_plan import build_aws_deck_plan
from app.services.office_identity.presentation_composer import build_presentation_from_plan
from app.services.office_identity.template_normalization import normalize_template
from app.services.office_identity.template_snapshot import build_template_snapshot, layout_by_key
from tests.office_generic_templates_support import TEMPLATE_NAMES, layout_of_shape, write_named_template
from tests.office_identity_aws_deck_plan_support import _aws_snapshot, _diagram_images, _knowledge_facts
from tests.office_template_fixture import png_bytes

#: Shapes the structure must yield per template — no layout name involved for
#: ``default`` sections or anything in ``neutral``.
EXPECTED_SHAPES = {
    "brand": {"title_slide", "section", "icons_3", "bullets", "agenda", "statement"},
    "default": {"title_slide", "section", "bullets", "columns_2", "two_content"},
    "neutral": {"title_slide", "section", "icons_3", "bullets", "title_and_subtitle"},
}
_DIVIDER = re.compile(r"^Slide source: Planner: section \d", re.MULTILINE)
TOPIC_SHAPE = {"brand": "icons_3", "default": None, "neutral": "icons_3"}

_GENERIC_CONTENT = {
    "title": "Release review",
    "subtitle": "What changed this quarter",
    "sections": [
        {"heading": f"Area {n}", "bullets": [{"text": f"Change {n}", "source": f"commit {n}"}]}
        for n in range(1, 7)
    ],
    "open_points": ["Confirm the release date"],
}


@pytest.fixture(scope="module", params=TEMPLATE_NAMES)
def template(request, tmp_path_factory) -> tuple[str, Path, dict[str, Any]]:
    path = write_named_template(tmp_path_factory.mktemp(request.param), request.param)
    return request.param, path, build_template_snapshot(path)


@pytest.fixture(scope="module")
def aws_deck(template, tmp_path_factory) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    name, path, snapshot = template
    folder = tmp_path_factory.mktemp(f"{name}-deck")
    diagram = folder / "aws-overview.png"
    diagram.write_bytes(png_bytes(1600, 900, (255, 255, 255)))
    plan = build_aws_deck_plan(
        _aws_snapshot(), snapshot, knowledge_facts=_knowledge_facts(), diagram_images=_diagram_images(diagram)
    )
    output = folder / "deck.pptx"
    result = build_presentation_from_plan(path, snapshot, plan, output)
    return plan, result, output


def _first_slide_texts(output: Path) -> dict[str, str]:
    from pptx import Presentation

    slide = Presentation(str(output)).slides[0]
    texts = {}
    for shape in slide.placeholders:
        kind = str(shape.placeholder_format.type).split(".")[-1].split(" ")[0].lower()
        texts[kind] = shape.text_frame.text if shape.has_text_frame else ""
    return texts


def test_layouts_are_detected_by_structure(template):
    name, _path, snapshot = template
    shapes = {layout["content_shape"] for layout in snapshot["layouts"]}
    assert EXPECTED_SHAPES[name] <= shapes


def test_title_slide_keeps_a_title_layout_with_title_and_subtitle(template, aws_deck):
    name, _path, snapshot = template
    plan, result, output = aws_deck
    title_layout = layout_by_key(snapshot, result["layout_keys"][0])
    assert title_layout["content_shape"] == "title_slide"
    assert title_layout["capacity"]["title_slots"] == 1 and title_layout["capacity"]["subtitle_slots"] == 1
    assert plan[0]["subtitle"].startswith("Regions: eu-central-1")
    assert "Subtitle placeholder" not in "\n".join(entry["notes"] for entry in plan)
    texts = _first_slide_texts(output)
    assert any("account 123456789012" in text for text in texts.values())
    if title_layout["capacity"]["content_units"]:
        # brand and neutral: the title layout has a third text slot, which
        # carries the date as its own strapline line
        assert plan[0]["bullets"] == ["As of: 2026-07-20"]
        assert "As of" not in plan[0]["subtitle"]
    else:
        assert name == "default"
        # title + subtitle only: the date joins the subtitle, the layout is kept
        assert "bullets" not in plan[0]
        assert plan[0]["subtitle"].endswith("As of: 2026-07-20")
        assert "generated_at (2026-07-20T09:15:00+00:00)" in plan[0]["notes"]


def test_dividers_use_the_section_layout(template, aws_deck):
    _name, _path, snapshot = template
    plan, result, _output = aws_deck
    dividers = [index for index, entry in enumerate(plan) if _DIVIDER.search(entry["notes"])]
    assert dividers, "the AWS deck is large enough to earn dividers"
    for index in dividers:
        assert plan[index]["content_shape"] == "section"
        assert layout_by_key(snapshot, result["layout_keys"][index])["content_shape"] == "section"


def test_topics_slide_uses_a_three_column_layout_where_one_exists(template, aws_deck):
    name, _path, _snapshot = template
    plan, _result, _output = aws_deck
    topics = [entry for entry in plan if entry["title"] == "The survey in three numbers"]
    if TOPIC_SHAPE[name] is None:
        # no three-column layout: the figures stay bullets on the overview
        assert topics == []
        overview = next(entry for entry in plan if entry["title"] == "Overview and key figures")
        assert any("distinct resource types" in bullet for bullet in overview["bullets"])
        return
    assert len(topics) == 1 and topics[0]["content_shape"] == TOPIC_SHAPE[name]
    assert topics[0]["icon_topics"] == ["resource_types", "services", "regions"]


def test_topics_slide_falls_back_to_plain_columns(tmp_path):
    path = write_named_template(tmp_path, "neutral-plain")
    snapshot = build_template_snapshot(path)
    assert layout_of_shape(snapshot, "columns_3") and not layout_of_shape(snapshot, "icons_3")
    plan = build_aws_deck_plan(_aws_snapshot(), snapshot, knowledge_facts=_knowledge_facts())
    topics = [entry for entry in plan if entry["title"] == "The survey in three numbers"]
    assert len(topics) == 1 and topics[0]["content_shape"] == "columns_3"
    result = build_presentation_from_plan(path, snapshot, plan, tmp_path / "plain.pptx")
    assert result["slide_count"] == len(plan)


def test_generic_deck_plan_keeps_title_and_section_layouts(template, tmp_path):
    _name, path, snapshot = template
    plan = build_generic_deck_plan(_GENERIC_CONTENT, snapshot)
    # never the divider: a title layout carrying title and subtitle
    assert plan[0]["content_shape"] in {"title_slide", "title_and_subtitle"}
    assert plan[0]["subtitle"] == "What changed this quarter"
    dividers = [entry for entry in plan if _DIVIDER.search(entry["notes"])]
    assert dividers and all(entry["content_shape"] == "section" for entry in dividers)
    result = build_presentation_from_plan(path, snapshot, plan, tmp_path / "generic.pptx")
    cover = layout_by_key(snapshot, result["layout_keys"][0])
    assert cover["content_shape"] == plan[0]["content_shape"]
    assert cover["capacity"]["title_slots"] == 1 and cover["capacity"]["subtitle_slots"] == 1
    assert not [f for f in result["quality_findings"] if f["slide_index"] == 0 and f["severity"] != "info"]


def test_normalization_keeps_the_structural_catalog(template, tmp_path):
    name, path, snapshot = template
    report = normalize_template(path, tmp_path / f"normalized{path.suffix}")
    assert report["status"] in {"normalized", "unchanged"}
    normalized = Path(report["output_path"]) if report["output_path"] else path
    after = build_template_snapshot(normalized)
    shapes = {layout["content_shape"] for layout in after["layouts"]}
    assert EXPECTED_SHAPES[name] <= shapes
    assert len(after["layouts"]) >= len(snapshot["layouts"])
