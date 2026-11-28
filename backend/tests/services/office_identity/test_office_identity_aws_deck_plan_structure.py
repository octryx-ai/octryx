"""The deck plan follows the documented order deterministically and binds every bullet to a snapshot source."""

from __future__ import annotations

from typing import Any

from app.services.office_identity.aws_deck_entries import OPEN_POINTS_TITLE
from app.services.office_identity.aws_deck_plan import build_aws_deck_plan
from tests.services.office_identity.office_identity_aws_deck_plan_support import (
    _aws_snapshot,
    _diagram_images,
    _knowledge_facts,
    _minimal_template,
    _note_lines,
    _plan,
)


def _entry(plan: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    matches = [entry for entry in plan if str(entry.get("title", "")).startswith(prefix)]
    assert len(matches) == 1, [entry.get("title") for entry in plan]
    return matches[0]


def _titled(titles: list[str], prefix: str) -> str:
    matches = [title for title in titles if title.startswith(prefix)]
    assert len(matches) == 1, titles
    return matches[0]


def test_plan_follows_the_documented_order():
    facts = _knowledge_facts() + [
        {"statement": "Der Betrieb erfolgt rund um die Uhr", "source": "knowledge:ops"}
    ]
    plan = _plan(_minimal_template(), diagram_images=_diagram_images(), knowledge_facts=facts)
    titles = [entry["title"] for entry in plan]

    network = _titled(titles, "Network foundation")

    assert titles[0].startswith("AWS architecture — account 123456789012")
    assert titles[1] == "Agenda"
    assert titles[2] == "41 resources recorded"
    assert titles[3] == "Overview and key figures"
    assert titles[4] == "Survey coverage"
    # The diagram block holds one slide, so structure dosing puts no
    # section divider before it — the diagram follows the coverage slide.
    assert titles[5] == "AWS topology — overview"
    assert "Domain context" in titles
    assert titles[-1].startswith(OPEN_POINTS_TITLE)
    assert titles.index(network) > titles.index("AWS topology — overview")
    assert titles.index("Domain context") > titles.index(network)


def test_title_slide_dates_itself_from_generated_at():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    title = plan[0]
    assert title["subtitle"] == "Regions: eu-central-1, eu-west-1"
    assert title["bullets"] == ["As of: 2026-07-20"]
    assert "Source: generated_at (2026-07-20T09:15:00+00:00)" in title["notes"]


def test_shape_choice_prefers_an_exactly_filled_layout():
    template = _minimal_template()
    with_date = _plan(template, diagram_images=_diagram_images())
    assert with_date[0]["content_shape"] == "title_slide"

    snapshot = _aws_snapshot()
    snapshot.pop("generated_at")
    without_date = build_aws_deck_plan(snapshot, template, diagram_images=_diagram_images())
    assert "bullets" not in without_date[0]
    assert without_date[0]["content_shape"] == "title_and_subtitle"


def test_plan_is_deterministic():
    template = _minimal_template()
    first = _plan(template, diagram_images=_diagram_images(), knowledge_facts=_knowledge_facts())
    second = _plan(template, diagram_images=_diagram_images(), knowledge_facts=_knowledge_facts())
    assert first == second


def test_every_bullet_carries_its_source_in_the_notes():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images(), knowledge_facts=_knowledge_facts())
    unsourced: list[tuple[str, str]] = []
    for entry in plan:
        lines = _note_lines(entry)
        for bullet in entry.get("bullets") or []:
            sourced = any(bullet in line and "Source:" in line for line in lines)
            if not sourced:
                unsourced.append((entry["title"], bullet))
    assert unsourced == [], f"bullets without a source in the notes: {unsourced}"


def test_a_bullet_without_a_source_would_fail_the_check():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    entry = next(item for item in plan if item.get("bullets"))
    entry["bullets"].append("The platform is highly available")
    lines = _note_lines(entry)
    assert not any("The platform is highly available" in line and "Source:" in line for line in lines)


def test_bullets_name_real_snapshot_fields():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    overview = next(entry for entry in plan if entry["title"] == "Overview and key figures")
    notes = overview["notes"]
    assert "Source: scope.regions" in notes
    assert "Source: service_summary.inventory_services_with_resources" in notes
    assert "Regions: eu-central-1, eu-west-1" in overview["bullets"]
    statement = next(entry for entry in plan if entry["title"] == "41 resources recorded")
    assert statement["subtitle"] == "and 57 relationships between them"
    assert "Slide source: service_summary.resource_node_count" in statement["notes"]
    assert "Source: service_summary.edge_count" in statement["notes"]
    assert not [line for line in overview["bullets"] if "resources recorded" in line]


def test_theme_slides_are_built_from_node_counts_by_type():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    network = _entry(plan, "Network foundation")
    assert network["title"] == "Network foundation — 6 resource kinds"
    assert "6 subnets" in network["bullets"]
    assert "1 VPC" in network["bullets"]
    assert all("Source: service_summary.node_counts_by_type" in line for line in _note_lines(network)[1:7])

    security = _entry(plan, "Identity and security")
    assert "7 security groups" in security["bullets"]
    assert "6 IAM roles" in security["bullets"]


def test_unknown_node_type_is_listed_not_guessed_into_a_theme():
    plan = _plan(_minimal_template(), diagram_images=_diagram_images())
    extra = _entry(plan, "Further recorded resource types")
    assert "6 resources of type \"quantum_flux_capacitor\"" in extra["bullets"]
    assert any("[DECISION:" in line for line in _note_lines(extra))
