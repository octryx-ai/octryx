"""Markers and open points in the deck plan: node caps, diagrams, knowledge facts and robustness on small or odd input."""

from __future__ import annotations

from app.services.office_identity.aws_deck_entries import OPEN_POINTS_TITLE
from app.services.office_identity.aws_deck_evidence import MARKER_PREFIXES, is_marker
from app.services.office_identity.aws_deck_plan import build_aws_deck_plan
from tests.services.office_identity.office_identity_aws_deck_plan_support import (
    DIAGRAM_PNG,
    _aws_snapshot,
    _diagram_images,
    _knowledge_facts,
    _minimal_template,
    _note_lines,
    _plan,
)

# ---------------------------------------------------------------------------
# visible 20 % (rule 3)
# ---------------------------------------------------------------------------


def test_open_points_slide_lists_skipped_and_partial_services():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images(), knowledge_facts=_knowledge_facts())
    open_points = [entry for entry in plan if entry["title"].startswith(OPEN_POINTS_TITLE)]
    assert open_points
    bullets = [bullet for entry in open_points for bullet in entry["bullets"]]

    assert any("lambda" in bullet and "services_skipped" in bullet for bullet in bullets)
    assert any("s3" in bullet and "services_partial" in bullet for bullet in bullets)
    assert any("s3" in bullet and "services_failed" in bullet for bullet in bullets)
    assert all(is_marker(bullet) for bullet in bullets)


def test_every_marker_reaches_the_open_points_slide():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    open_titles = {entry["title"] for entry in plan if entry["title"].startswith(OPEN_POINTS_TITLE)}
    listed = {
        bullet
        for entry in plan
        if entry["title"] in open_titles
        for bullet in entry["bullets"]
    }
    in_notes = {
        line
        for entry in plan
        if entry["title"] not in open_titles
        for line in _note_lines(entry)
        if line.startswith(MARKER_PREFIXES)
    }
    assert in_notes and in_notes <= listed


def test_warnings_produce_a_check_number_marker():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    coverage = next(entry for entry in plan if entry["title"] == "Survey coverage")
    assert "2 warning(s) in the snapshot" in coverage["bullets"]
    assert any("[CHECK NUMBER:" in line and "warning" in line for line in _note_lines(coverage))


def test_node_count_at_the_cap_is_flagged():
    snapshot = _aws_snapshot()
    snapshot["scope"]["max_nodes"] = 41
    plan = build_aws_deck_plan(snapshot, _minimal_template(), diagram_images=_diagram_images())
    overview = next(entry for entry in plan if entry["title"] == "Overview and key figures")
    assert any("max_nodes=41" in line and "[CHECK NUMBER:" in line for line in _note_lines(overview))


# ---------------------------------------------------------------------------
# diagrams come from the pipeline (rule 4)
# ---------------------------------------------------------------------------


def test_diagram_slides_carry_image_role_and_the_diagram_id():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    diagram = next(entry for entry in plan if entry.get("image_slots"))
    assert diagram["image_role"] == "diagram"
    assert diagram["image_slots"] == [str(DIAGRAM_PNG)]
    assert diagram["content_shape"] == "diagram_full"
    assert "aws-overview-dcd76f69" in diagram["notes"]
    assert "bullets" not in diagram


def test_missing_diagram_is_a_marker_not_a_drawn_slide():
    plan = _plan(_minimal_template())
    assert not any(entry.get("image_slots") for entry in plan)
    bullets = [
        bullet
        for entry in plan
        if entry["title"].startswith(OPEN_POINTS_TITLE)
        for bullet in entry["bullets"]
    ]
    assert any("Diagram PNG" in bullet and "[SOURCE MISSING:" in bullet for bullet in bullets)


def test_diagram_without_a_title_uses_the_file_stem_and_says_so():
    plan = _plan(_minimal_template(), diagram_images=[str(DIAGRAM_PNG)])
    diagram = next(entry for entry in plan if entry.get("image_slots"))
    assert diagram["title"] == DIAGRAM_PNG.stem
    assert any("[SOURCE MISSING:" in line and "Title for diagram" in line for line in _note_lines(diagram))


# ---------------------------------------------------------------------------
# knowledge facts (rule 6)
# ---------------------------------------------------------------------------


def test_empty_knowledge_facts_produce_a_marker_and_no_section():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    assert not any(entry["title"] == "Domain context" for entry in plan)
    bullets = [
        bullet
        for entry in plan
        if entry["title"].startswith(OPEN_POINTS_TITLE)
        for bullet in entry["bullets"]
    ]
    assert any("Knowledge context" in bullet and "[SOURCE MISSING:" in bullet for bullet in bullets)


def test_knowledge_fact_without_a_source_never_becomes_a_bullet():
    facts = _knowledge_facts() + [{"statement": "Everything is built redundantly"}]
    plan = _plan(_minimal_template(), diagram_images=_diagram_images(), knowledge_facts=facts)
    context = next(entry for entry in plan if entry["title"] == "Domain context")
    # The sourceless fact becomes a marker, never a bullet — and the context
    # slide survives to carry that marker even though every sourced fact has
    # moved onto its theme slide.
    assert not context.get("bullets")
    assert any("[SOURCE MISSING:" in line and "Everything is built redundantly" in line for line in _note_lines(context))
    # The sourced fact travels with its evidence to the theme it belongs to.
    runtime = next(entry for entry in plan if entry["title"].startswith("Compute"))
    assert "knowledge:knowledge_graph:node/platform-runtime" in runtime["notes"]


# ---------------------------------------------------------------------------
# robustness
# ---------------------------------------------------------------------------


def test_tiny_snapshot_still_yields_a_valid_plan():
    plan = build_aws_deck_plan({"account_id": "1"}, _minimal_template())
    assert plan
    assert plan[0]["title"] == "AWS architecture — account 1"
    assert plan[-1]["title"].startswith(OPEN_POINTS_TITLE)
    for entry in plan:
        assert entry["notes"]
        assert entry["title"]


def test_empty_snapshot_does_not_raise():
    plan = build_aws_deck_plan({}, _minimal_template())
    assert plan[0]["title"] == "AWS architecture"
    bullets = [
        bullet
        for entry in plan
        if entry["title"].startswith(OPEN_POINTS_TITLE)
        for bullet in entry["bullets"]
    ]
    assert any("account_id" in bullet for bullet in bullets)


def test_template_without_a_subtitle_layout_marks_the_dropped_subtitle():
    template = _minimal_template()
    for layout in template["layouts"]:
        layout["capacity"]["subtitle_slots"] = 0
    plan = build_aws_deck_plan(_aws_snapshot(), template, diagram_images=_diagram_images())
    assert "subtitle" not in plan[0]
    bullets = [
        bullet
        for entry in plan
        if entry["title"].startswith(OPEN_POINTS_TITLE)
        for bullet in entry["bullets"]
    ]
    assert any("Subtitle placeholder" in bullet for bullet in bullets)


def test_open_points_are_split_across_slides_when_they_do_not_fit():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    open_points = [entry for entry in plan if entry["title"].startswith(OPEN_POINTS_TITLE)]
    assert len(open_points) > 1
    assert open_points[0]["title"].endswith(f"(1/{len(open_points)})")
    assert all(len(entry["bullets"]) <= 6 for entry in open_points)
