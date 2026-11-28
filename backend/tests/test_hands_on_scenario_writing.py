"""Scenarios use only the app's own texts, get three answers each with every refusal told, can be waived or rewritten by an admin, and never click a generic save the changed screens do not show."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.workflow_runs.hands_on import step
from app.services.workflow_runs.hands_on.scenarios import COVERS, validate
from tests.hands_on_support import _answer, _at_hands_on, _Model
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_scenarios_use_only_the_apps_own_texts_and_are_asked_again_otherwise(tmp_path):
    import json

    from app.services.workflow_runs.hands_on.generate import ui_texts, unknown_texts, write_scenarios

    l10n = tmp_path / "coffee" / "lib" / "l10n"
    l10n.mkdir(parents=True)
    (l10n / "app_en.arb").write_text(json.dumps({"@@locale": "en", "skip": "Skip", "@skip": {}, "scaleStep": "Scale step"}))
    (l10n / "app_de.arb").write_text(json.dumps({"@@locale": "de", "skip": "Überspringen", "scaleStep": "Schritt"}))
    texts = ui_texts(tmp_path)
    # Only the English catalog: the hands-on browser starts in English.
    assert texts == ["Skip", "Scale step"]
    german_click = [{"steps": [{"do": "goto", "path": "/"}, {"do": "click", "text": "Überspringen"}]}]
    assert unknown_texts(german_click, texts) == ["Überspringen"]
    german_only = tmp_path / "de_only" / "lib" / "l10n"
    german_only.mkdir(parents=True)
    (german_only / "app_de.arb").write_text(json.dumps({"skip": "Überspringen"}))
    assert ui_texts(tmp_path / "de_only") == ["Überspringen"]  # no English catalog: the app's own texts
    wrong = _answer()
    wrong["scenarios"][0]["steps"] = [{"do": "goto", "path": "/"}, {"do": "fill", "label": "Totraum (g)", "value": "M1"},
                                      {"do": "click", "text": "M1"}, {"do": "click", "text": "Skip"}]
    assert unknown_texts(validate(wrong), texts) == ["Totraum (g)"]  # a typed value may be clicked
    model = _Model(wrong, _answer())
    scenarios, problem, _usage = await write_scenarios(None, SimpleNamespace(id="r"), model, "task", texts)
    assert problem == "" and len(scenarios) == 4
    assert "not texts the app has: Totraum (g)" in model.asked[1]


@pytest.mark.asyncio
async def test_the_scenarios_get_three_answers_each_told_every_refusal():
    from app.services.workflow_runs.hands_on.generate import write_scenarios

    wrong_label = _answer()
    wrong_label["scenarios"][0]["steps"] = [{"do": "fill", "label": "Totraum (g)", "value": "1"}]
    no_cover = {"scenarios": _answer()["scenarios"][:2]}
    model = _Model(wrong_label, no_cover, _answer())
    scenarios, problem, _usage = await write_scenarios(None, SimpleNamespace(id="r"), model, "task", ["Skip"], required=COVERS)
    assert problem == "" and len(scenarios) == 4
    assert "Totraum (g)" in model.asked[2] and "do not cover" in model.asked[2]


@pytest.mark.asyncio
async def test_when_no_answer_holds_the_reason_names_each_attempt_in_order():
    from app.services.workflow_runs.hands_on.generate import write_scenarios

    wrong_label = _answer()
    wrong_label["scenarios"][0]["steps"] = [{"do": "fill", "label": "Totraum (g)", "value": "1"}]
    no_cover = {"scenarios": _answer()["scenarios"][:2]}
    model = _Model(wrong_label, no_cover, no_cover)
    scenarios, problem, _usage = await write_scenarios(None, SimpleNamespace(id="r"), model, "task", ["Skip"], required=COVERS)
    assert scenarios == [] and problem.startswith("the scenarios could not be written: attempt 1: ")
    first, second, third = problem.removeprefix("the scenarios could not be written: ").split("; attempt ")
    assert "Totraum (g)" in first and second.startswith("2: ") and "do not cover" in second
    assert third.startswith("3: ") and "do not cover" in third


@pytest.mark.asyncio
async def test_an_admin_waives_scenarios_for_every_further_pass_with_the_reason_kept(db, monkeypatch):
    from app.services.workflow_runs.actions import perform_action
    from app.services.workflow_runs.records import WorkflowRunError
    from tests.phased_workflow_fixtures import admin_user
    from tests.policy_engine_support import make_user

    run, session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    admin = await admin_user(db)
    other = await db.get(type(admin), await make_user(db, admin=False))
    body = {"action": "waive_hands_on_scenarios", "scenarios": ["S2", "repo:tests/hands_on/bugs/X.json#1"],
            "reason": "S2 fails on the open bug OCX-73"}
    with pytest.raises(WorkflowRunError):
        await perform_action(db, run, user=other, body=body)
    await perform_action(db, run, user=admin, body=body)
    view = step.contract_view(run)
    assert [item["id"] for item in view["scenarios"]] == ["S1", "S3", "S4"]
    report = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "scenarios": [
        {"id": "S1", "passed": True}, {"id": "S3", "passed": True}, {"id": "S4", "passed": True},
        {"id": "repo:tests/hands_on/bugs/X.json#1", "passed": False, "failed_step": 1}]}
    assert await step.record_report(db, run, report, session_id=session.id) == "green"
    waived = [item for item in step.run_view(run)["results"] if item.get("waived")]
    assert [item["id"] for item in waived] == ["S2", "repo:tests/hands_on/bugs/X.json#1"]
    assert waived[0]["waived"] == "waived by admin (S2 fails on the open bug OCX-73)"


@pytest.mark.asyncio
async def test_an_admin_has_the_scenarios_written_again_and_the_waiting_pass_regenerates(db, monkeypatch):
    from app.services.workflow_runs.actions import perform_action
    from app.services.workflow_runs.records import WorkflowRunError
    from tests.phased_workflow_fixtures import admin_user
    from tests.policy_engine_support import make_user

    run, _session, _offered, factory = await _at_hands_on(db, monkeypatch, model=_Model(_answer(), _answer()))
    await step.generate_due(db, model_factory=factory)
    run = await db.get(type(run), run.id)
    assert step.state(run)["state"] == "pending" and len(step.contract_view(run)["scenarios"]) == 4
    admin = await admin_user(db)
    other = await db.get(type(admin), await make_user(db, admin=False))
    await perform_action(db, run, user=admin, body={"action": "waive_hands_on_scenarios", "scenarios": ["S2"],
                                                    "reason": "scenario defect"})
    body = {"action": "regenerate_hands_on_scenarios", "reason": "written from the German catalog"}
    with pytest.raises(WorkflowRunError):
        await perform_action(db, run, user=other, body=body)
    await perform_action(db, run, user=admin, body=body)
    assert step.state(run)["state"] == "generating" and step.contract_view(run) is None
    assert "hands_on_scenarios" not in run.context and "hands_on_waived" not in run.context
    assert await step.generate_due(db, model_factory=factory) == 1
    run = await db.get(type(run), run.id)
    view = step.contract_view(run)
    assert len(view["scenarios"]) == 4
    # The device's pass for the old set reports late (started before the regeneration): ignored, the new set offered.
    old = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "seconds": 600,
           "scenarios": [{"id": f"S{n}", "passed": False, "failed_step": 1} for n in range(1, 12)]}
    assert await step.record_report(db, run, old, session_id=_session.id) == "ignored"
    assert step.state(run)["state"] == "pending"
    fresh = {"node_id": view["node_id"], "entry": view["entry"], "state": "ran", "seconds": 0,
             "scenarios": [{"id": f"S{n}", "passed": True} for n in range(1, 5)]}
    assert await step.record_report(db, run, fresh, session_id=_session.id) == "green"


@pytest.mark.asyncio
async def test_a_feature_scenario_never_clicks_a_generic_save_the_changed_screens_do_not_show(tmp_path):
    import json

    from app.services.workflow_runs.hands_on.generate import foreign_clicks, screen_actions, write_scenarios

    app = tmp_path / "coffee"
    (app / "lib" / "l10n").mkdir(parents=True)
    (app / "lib" / "l10n" / "app_en.arb").write_text(json.dumps(
        {"save": "Save", "onboardingNext": "Next", "navEquipment": "Equipment", "onboardingLater": "Later"}))
    screen = app / "lib" / "features" / "onboarding" / "presentation"
    screen.mkdir(parents=True)
    (screen / "onboarding_actions.dart").write_text("Text(l.onboardingNext); Text(l.onboardingLater);\n")
    (screen / "onboarding_grinder_page.dart").write_text("class OnboardingGrinderPage {}\n")
    (app / "lib" / "features" / "equipment").mkdir(parents=True)
    (app / "lib" / "features" / "equipment" / "grinder_form.dart").write_text("Text(l.save);\n")
    changed = ("coffee/lib/features/onboarding/presentation/onboarding_grinder_page.dart",)
    actions = screen_actions(tmp_path, changed)
    assert actions == ["Next", "Later"]
    feature = [{"part": "feature", "steps": [{"do": "click", "text": "Next"}, {"do": "click", "text": "Save"},
                                             {"do": "click", "text": "Equipment"}]}]
    generic = ["save", "submit"]
    assert foreign_clicks(feature, actions, generic) == ["Save"]  # navigation to another screen stays allowed
    wrong = _answer()
    wrong["scenarios"][0]["steps"] = [{"do": "goto", "path": "/"}, {"do": "click", "text": "Save"}]
    model = _Model(wrong, _answer())
    scenarios, problem, _usage = await write_scenarios(None, SimpleNamespace(id="r"), model, "task", [], actions,
                                                       generic)
    assert problem == "" and "never assume a generic form button" in model.asked[1]
    assert foreign_clicks(feature, actions, []) == []


def test_the_generic_actions_are_workflow_data_not_engine_code():
    import json
    from pathlib import Path

    import app.services.workflow_runs.hands_on.generate as generate

    assert '"speichern"' not in Path(generate.__file__).read_text(encoding="utf-8")
    seeds = Path(generate.__file__).parents[1] / "seeds" / "phased_workflows.json"
    nodes = [node for workflow in json.loads(seeds.read_text(encoding="utf-8"))
             for node in dict(workflow.get("definition") or {}).get("nodes") or []
             if dict(node.get("config") or {}).get("action") == "hands_on.run"
             and node["config"].get("mode") != "reproduce"]
    assert nodes and all("save" in node["config"]["generic_actions"] for node in nodes)
