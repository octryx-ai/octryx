"""The app's draw.io diagrams in the code style: the agent's rule, the device's facts judged."""

from __future__ import annotations

import pytest

from app.services.code_style.brief import agent_brief, diagram_rule
from app.services.code_style.defaults import BUILT_IN
from app.services.code_style.diagrams import diagram_findings, reviewer_notes
from app.services.code_style.resolve import effective, flat
from app.services.code_style.schema import normalize_profile
from app.services.code_style.schema_values import CodeStyleError
from app.services.workflow_runs.octryx.code_limits import style_result


def _style(**general):
    return {"general": {**flat(effective({})), **general}, "languages": {}}


FACTS = {"tool": "missing", "os": "Darwin", "files": [
    {"path": "coffee/docs/diagrams/navigation.drawio", "png": "coffee/docs/images/navigation.png", "valid": True,
     "png_state": "missing_tool", "referenced": False, "unmatched": ["Settings"]},
    {"path": "coffee/docs/diagrams/broken.drawio", "png": "coffee/docs/images/broken.png", "valid": False,
     "error": "no element found"}]}


def test_diagrams_are_on_by_default_and_a_workspace_can_switch_them_off_or_move_them():
    assert BUILT_IN["diagrams"]["enabled"] is True and flat(effective({}))["diagrams"]["folder"] == "docs/diagrams"
    workspace = normalize_profile({"diagrams": {"enabled": False}})
    assert flat(effective({"workspace": workspace}))["diagrams"]["enabled"] is False
    moved = normalize_profile({"diagrams": {"folder": "doc/arch", "kinds": ["navigation"]}})
    assert flat(effective({"repository": moved}))["diagrams"]["images"] == "docs/images"  # merged per key
    for broken in ({"folder": "../x"}, {"kinds": ["sequence"]}, {"enabled": "yes"}, {"other": 1}):
        with pytest.raises(CodeStyleError):
            normalize_profile({"diagrams": broken})


def test_the_agent_is_told_to_update_the_existing_diagrams_with_real_names():
    rule = diagram_rule(BUILT_IN["diagrams"])
    assert "docs/diagrams/" in rule and "navigation.drawio" in rule and "never a second one" in rule
    assert "real module, class or screen name" in rule and "docs/images/<name>.png" in rule
    assert diagram_rule({"enabled": False}) == "" and "Diagrams:" in agent_brief(_style())


def test_the_findings_warn_by_default_and_missing_tool_error_makes_the_missing_cli_red():
    found = {(item.rule, item.severity) for item in diagram_findings(_style(), FACTS)}
    assert found == {("diagram_png", "warning"), ("diagram_labels", "warning"), ("diagram_xml", "error")}
    png = next(item for item in diagram_findings(_style(), FACTS) if item.rule == "diagram_png")
    assert "brew install --cask drawio" in png.message and "committed without it" in png.message
    strict = {(item.rule, item.severity) for item in diagram_findings(_style(missing_tool="error"), FACTS)}
    assert ("diagram_png", "error") in strict
    assert diagram_findings(_style(diagrams={"enabled": False}), FACTS) == []
    assert reviewer_notes(FACTS) == ["coffee/docs/diagrams/navigation.drawio: Settings"]


def test_the_stop_blocks_on_invalid_xml_and_only_warns_for_the_rest():
    result = style_result(_style(), {}, None, None, FACTS)
    assert result.blocking is True and "not valid draw.io XML" in result.description
    valid = {**FACTS, "files": [FACTS["files"][0]]}
    warned = style_result(_style(), {}, None, None, valid)
    assert warned.blocking is False and "draw.io CLI is missing" in warned.detail
