"""The composer works for any topic from sourced content, not only AWS."""

from app.services.office_identity import (
    build_generic_deck_plan,
    build_generic_document_plan,
)
from app.services.office_identity.aws_deck_sections import STATEMENT_SHAPES
from app.services.office_identity.aws_deck_slides import BULLET_SHAPES
from app.services.office_identity.generic_content_plan import (
    _TWO_COLUMN_SHAPES,
    _headline_draft,
    _section_draft,
)

_CONTENT = {
    "title": "Release 2.4.10",
    "subtitle": "Changes",
    "sections": [
        {"heading": "New features", "bullets": [{"text": "Word-Composer", "source": "commit a1"}]},
        {"heading": "Fixes", "bullets": [{"text": "Diagram set", "source": "commit b2"}]},
    ],
    "open_points": ["Confirm the release date"],
}


def test_document_plan_from_content_is_evidence_bound():
    plan = build_generic_document_plan(_CONTENT)
    kinds = [b["kind"] for b in plan]
    assert kinds[0] == "title"
    assert plan[0]["text"] == "Release 2.4.10"
    headings = [b["text"] for b in plan if b["kind"] == "heading"]
    assert "New features" in headings and "Open points" in headings
    markers = [b["text"] for b in plan if b["kind"] == "marker"]
    assert any("release date" in m for m in markers)


def test_document_section_without_source_is_flagged_not_invented():
    content = {"title": "X", "sections": [{"heading": "Empty"}]}
    plan = build_generic_document_plan(content)
    markers = [b["text"] for b in plan if b["kind"] == "marker"]
    assert any("[SOURCE MISSING:" in m and "Empty" in m for m in markers)


def test_deck_plan_from_content_needs_no_aws_snapshot():
    plan = build_generic_deck_plan(_CONTENT, {})
    titles = [entry.get("title") for entry in plan]
    assert titles[0] == "Release 2.4.10"
    assert "New features" in titles
    assert any("Open points" in str(t) for t in titles)


def test_sections_get_varied_slide_types_not_only_bullets():
    headline = _headline_draft({"statement": {"text": "8 Verbesserungen", "subtitle": "aus Evidenz"}})
    assert headline is not None and headline.shape_preference == STATEMENT_SHAPES

    statement = _section_draft({"type": "statement", "heading": "Everything from one source"})
    assert statement.shape_preference == STATEMENT_SHAPES

    two = _section_draft({"heading": "Zwei", "columns": [{"heading": "A", "text": "x"}, {"heading": "B", "text": "y"}]})
    assert two.shape_preference == _TWO_COLUMN_SHAPES and len(two.blocks) == 2

    three = _section_draft(
        {"heading": "Drei", "columns": [{"heading": h, "text": h} for h in ("A", "B", "C")]}
    )
    assert three.shape_preference == BULLET_SHAPES and len(three.bullets) == 3


def test_headline_is_never_invented():
    assert _headline_draft({}) is None
    assert _headline_draft({"statement": {"subtitle": "no text"}}) is None
