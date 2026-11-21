"""Spec Studio model: the artefact's shape, the spec gates from Bench Coffee and the product owner's audited changes.

Fixture: a real Flutter spec from a benchmark run as Studio data (``fixtures/spec_studio/caf44``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.workflow_runs.spec_studio.design import contrast, effective_design, on_accent
from app.services.workflow_runs.spec_studio.gates import needs_revision, open_points
from app.services.workflow_runs.spec_studio.schema import validate_spec_studio
from app.services.workflow_runs.spec_studio.state import StudioChangeError, apply_change, current_state

FIXTURE = Path(__file__).parent / "fixtures/spec_studio/caf44/studio.json"


def _raw() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _record(raw: dict | None = None) -> dict:
    record, problems = validate_spec_studio(raw or _raw())
    assert problems == []
    return record


def _points(record: dict, state: dict | None = None) -> list[str]:
    state = state or {}
    return [p["text"] for p in open_points(record, state, effective_design(record, state))]


def test_the_caf44_spec_is_a_complete_studio_with_no_open_point():
    record = _record()
    assert (record["mode"], record["target"], len(record["screens"]), len(record["questions"])) == (
        "new", "flutter", 5, 5)
    assert _points(record) == []


def test_the_tools_name_it_spec_mode_and_the_record_keeps_mode():
    """No MCP tool has a "mode" property (test_mcp_claude_code_parity: a mode reads as an agent mode)."""
    raw = _raw()
    raw.pop("mode", None)
    raw["spec_mode"] = "feature"
    record, _problems = validate_spec_studio(raw)
    assert record["mode"] == "feature"
    raw["spec_mode"] = "rewrite"
    assert any(p.startswith("spec_mode: one of") for p in validate_spec_studio(raw)[1])


def test_a_malformed_proposal_lists_every_problem_at_once():
    raw = _raw()
    raw["design"]["directions"][0]["light"]["accent"] = "brown"
    raw["screens"][0]["filled"].append({"type": "carousel"})
    raw["questions"][0]["proposal"] = "48"
    raw["screens"].append(copy.deepcopy(raw["screens"][1]))
    _record_, problems = validate_spec_studio(raw)
    assert any("light.accent" in p for p in problems)
    assert any(".type: one of" in p for p in problems)
    assert any("questions[purge].proposal" in p for p in problems)
    assert any("the id beans is used twice" in p for p in problems)


def test_the_bench_coffee_gaps_are_open_points():
    raw = _raw()
    raw["requirements"][1].pop("how")  # X1–X4: a prompt verb without a default that works on first launch
    raw["rules"][0]["examples"] = [{"given": "8.4 °dH", "expect": "149.9 ppm"}]  # C1: no realistic example
    raw["screens"][1]["empty"] = []  # C12/C15: no empty state
    raw["screens"][2]["next_step"] = ""
    raw["screens"][0]["filled"].append({"type": "text", "text": "Dein letzter Brew"})  # C14: glossary says Brühung
    raw["conditions"][0]["definition"] = ""  # X5/X8: undefined condition word
    points = " | ".join(_points(_record(raw)))
    assert "P2" in points and "zero configuration" in points
    assert "R1 Härte-Umrechnung: add one realistic example" in points
    assert "Bohnen: the empty state is missing" in points
    assert "Brühung erfassen: say what the next step is" in points
    assert "'Brew' is used; the glossary says 'Brühung'" in points
    assert "'trinkbereit': define it" in points


def test_contrast_follows_wcag_and_a_weak_colour_blocks_approval():
    assert round(contrast("#000000", "#FFFFFF"), 1) == 21.0
    assert on_accent("#8A4B2A") == "#FFFFFF" and on_accent("#E0A06A") == "#1A1410"
    record = _record()
    state = {"tokens": {"dark": {"muted": "#5A4A3E"}}}
    assert any("Muted text on card (dark)" in p for p in _points(record, state))


def _run(record: dict) -> SimpleNamespace:
    return SimpleNamespace(context={"outputs": {"spec_studio": {"record": record, "hash": "h1", "version": 1}}},
                           current_node_id="decisions")


def test_each_change_is_validated_and_audited_with_before_and_after():
    record = _record()
    run = _run(record)
    detail = apply_change(run, record, {"op": "answer", "question": "purge", "value": "24"}, by="po")
    assert detail == {"op": "answer", "target": "question:purge", "from": None, "to": {"value": "24"}, "by": "po"}
    apply_change(run, record, {"op": "answer", "question": "purge", "value": "2"}, by="po")  # back to the proposal
    assert current_state(run)["answers"] == {}
    apply_change(run, record, {"op": "design", "theme": "light", "key": "accent", "value": "#7a3f20"}, by="po")
    assert current_state(run)["tokens"] == {"light": {"accent": "#7A3F20"}}
    pinned = apply_change(run, record, {"op": "comment.add", "screen": "today", "device": "phone", "x": 120.4,
                                        "y": 812, "element": "Heute", "path": "nav.today",
                                        "text": "nicht Namen sondern Icons"}, by="po")
    assert pinned["to"]["x"] == 120 and pinned["to"]["device"] == "phone"
    for bad in ({"op": "answer", "question": "nope", "value": "x"},
                {"op": "design", "theme": "light", "key": "accent", "value": "red"},
                {"op": "comment.add", "screen": "nowhere"}, {"op": "teleport"}):
        with pytest.raises(StudioChangeError):
            apply_change(run, record, bad, by="po")
    with pytest.raises(StudioChangeError, match="frozen"):
        apply_change(run, record, {"op": "answer", "question": "purge", "value": "24"}, by="po", frozen=True)


def test_changed_rule_values_and_rejected_criteria_need_a_revision_not_an_approval():
    record = _record()
    run = _run(record)
    apply_change(run, record, {"op": "rule", "rule": "R10", "param": "ratio", "value": "15"}, by="po")
    apply_change(run, record, {"op": "acceptance", "id": "AC-3", "verdict": "change", "note": "1:15"}, by="po")
    state = current_state(run)
    points = open_points(record, state, effective_design(record, state))
    assert len(points) == 2 and needs_revision(points)
    apply_change(run, record, {"op": "rule", "rule": "R10", "param": "ratio", "value": "16"}, by="po")
    apply_change(run, record, {"op": "acceptance", "id": "AC-3", "verdict": "ok"}, by="po")
    state = current_state(run)
    assert open_points(record, state, effective_design(record, state)) == []


def test_a_feature_without_its_own_design_uses_the_approved_apps_tokens():
    raw = _raw()
    base = {"design": copy.deepcopy(_record()["design"])}
    raw.update(mode="feature", design={}, glossary=raw["glossary"], requirements=[])
    record = _record(raw)
    design = effective_design(record, {}, base)
    assert design["direction"] == "crema" and design["light"]["accent"] == "#8A4B2A"
    assert not any("requirement" in p for p in _points(record))  # a feature lists only its own requirements
