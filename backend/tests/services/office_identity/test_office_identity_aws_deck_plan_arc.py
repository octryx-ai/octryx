"""The presentation arc on a corporate-like template: structural shapes, readable statements, numbers from the snapshot and section dividers."""

from __future__ import annotations

import re

from app.services.office_identity.aws_deck_labels import numbers_in, permitted_numbers
from tests.services.office_identity.office_identity_aws_deck_plan_support import (
    _aws_snapshot,
    _corporate_template,
    _diagram_images,
    _knowledge_facts,
    _minimal_template,
    _plan,
)


def test_deck_uses_the_structural_shapes_the_template_offers():
    plan = _plan(
        _corporate_template(),
        diagram_images=_diagram_images(),
        knowledge_facts=_knowledge_facts(),
    )
    shapes = [entry.get("content_shape") for entry in plan]

    assert plan[1]["title"] == "Agenda"
    assert plan[1]["content_shape"] == "agenda"
    # Structure dosing: a divider is only worth its slide before a block of
    # at least two content slides, so the multi-slide resource block earns one
    # while the single-slide diagram block does not.
    assert shapes.count("section") >= 1, shapes
    assert "statement" in shapes
    assert "icons_3" in shapes
    # the sections that do appear are announced by the agenda
    section_titles = [entry["title"] for entry in plan if entry.get("content_shape") == "section"]
    assert set(section_titles).issubset(set(plan[1]["bullets"]))


def test_deck_uses_at_least_four_different_layout_shapes():
    plan = _plan(
        _corporate_template(),
        diagram_images=_diagram_images(),
        knowledge_facts=_knowledge_facts(),
    )
    shapes = {entry.get("content_shape") for entry in plan if entry.get("content_shape")}
    assert len(shapes) >= 4, shapes


def test_three_topics_slide_carries_three_sourced_columns():
    plan = _plan(_corporate_template(), diagram_images=_diagram_images())
    topics = next(entry for entry in plan if entry.get("content_shape") == "icons_3")
    assert len(topics["blocks"]) == 3
    for block in topics["blocks"]:
        assert block["heading"].isdigit()
        assert block["bullets"]
    # every column line is sourced in the notes
    assert topics["notes"].count("| Source:") == 3


def test_three_topics_slide_carries_icon_topic_keys():
    plan = _plan(_corporate_template(), diagram_images=_diagram_images())
    topics = next(entry for entry in plan if entry.get("content_shape") == "icons_3")
    assert topics["icon_topics"] == ["resource_types", "services", "regions"]


def test_no_bullet_is_a_raw_field_dump():
    dump = re.compile(r"^\w+:\s*\d+$")
    for template in (_minimal_template(), _corporate_template()):
        plan = _plan(template, diagram_images=_diagram_images(), knowledge_facts=_knowledge_facts())
        for entry in plan:
            for bullet in entry.get("bullets") or ():
                assert not dump.match(bullet), bullet
            for block in entry.get("blocks") or ():
                for bullet in block.get("bullets") or ():
                    assert not dump.match(bullet), bullet


def test_every_number_on_a_slide_comes_from_the_snapshot():
    snapshot = _aws_snapshot()
    allowed = permitted_numbers(snapshot)
    plan = _plan(
        _corporate_template(),
        diagram_images=_diagram_images(),
        knowledge_facts=_knowledge_facts(),
    )
    for entry in plan:
        texts = [entry.get("title") or "", entry.get("subtitle") or ""]
        texts.extend(entry.get("bullets") or ())
        for block in entry.get("blocks") or ():
            texts.append(block.get("heading") or "")
            texts.extend(block.get("bullets") or ())
        for text in texts:
            unsourced = numbers_in(text) - allowed
            assert not unsourced, f"{text!r} states {sorted(unsourced)}, absent from the snapshot"


def test_the_number_check_would_catch_an_invented_figure():
    allowed = permitted_numbers(_aws_snapshot())
    assert numbers_in("83 % of the resources are in production") - allowed


def test_arc_is_deterministic():
    first = _plan(_corporate_template(), diagram_images=_diagram_images())
    second = _plan(_corporate_template(), diagram_images=_diagram_images())
    assert first == second


def test_section_divider_prefers_a_layout_that_paints_its_own_backdrop():
    template = _corporate_template()
    template["layouts"].append(
        {
            "key": "section-header-blue",
            "content_shape": "section",
            "order": 14,
            "has_background": True,
            "capacity": {
                "content_units": 0,
                "picture_slots": 0,
                "title_slots": 1,
                "subtitle_slots": 1,
            },
        }
    )
    plan = _plan(template, diagram_images=_diagram_images())
    sections = [entry for entry in plan if entry.get("content_shape") == "section"]
    assert sections
    assert {entry["layout_key"] for entry in sections} == {"section-header-blue"}


def test_without_a_painted_section_layout_the_template_order_still_decides():
    plan = _plan(_corporate_template(), diagram_images=_diagram_images())
    sections = [entry for entry in plan if entry.get("content_shape") == "section"]
    assert sections
    # only one section layout, and no backdrop rule fires: no key is forced
    assert all("layout_key" not in entry for entry in sections)
