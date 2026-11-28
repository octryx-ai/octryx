"""Every workflow: an independent review that lists the assumptions the change makes beyond the spec, and the product owner's answers going back to the agent."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.phase_contract import phase_definition
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.review.verdict import parse_verdict
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"


def test_a_verdict_keeps_the_assumptions_and_a_malformed_list_never_drops_the_verdict():
    verdict = parse_verdict({"verdict": "pass", "summary": "ok", "findings": [],
                             "assumptions": ["Not in the inventory gives bonus 5: intended?", "", 7]})
    assert verdict.assumptions == ("Not in the inventory gives bonus 5: intended?", "7")
    assert verdict.to_dict()["assumptions"] == list(verdict.assumptions)
    plain = parse_verdict({"verdict": "pass", "summary": "ok", "findings": [], "assumptions": "none"})
    assert plain is not None and plain.assumptions == () and "assumptions" not in plain.to_dict()


def _definition(subject: str = "decisions") -> dict:
    return {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
            {"id": "decisions", "type": "user_confirmation", "label": "Ship or answer",
             "config": {"subject": subject}},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
            {"id": "stopped", "type": "outcome", "config": {"outcome": "stopped"}},
        ],
        "edges": [
            {"id": "a", "source_node_id": "start", "target_node_id": "work"},
            {"id": "b", "source_node_id": "work", "target_node_id": "decisions"},
            {"id": "c", "source_node_id": "decisions", "target_node_id": "done", "when": "confirmed"},
            {"id": "d", "source_node_id": "decisions", "target_node_id": "work", "when": "changed", "kind": "loop",
             "max_iterations": 3},
            {"id": "e", "source_node_id": "decisions", "target_node_id": "stopped", "when": "stopped"},
        ],
    }


@pytest.mark.asyncio
async def test_the_product_owners_answer_is_required_and_reaches_the_agents_next_pass(client, auth_headers, db):
    admin = await admin_user(db)
    key = await publish_phased(db, _definition())
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, session=session, project_id=workspace_id)
    resolution = await run_turn_resolution(db, session, user_message="Do it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    assert (run.waiting_kind, run.node_state["waiting"]["subject"]) == ("awaiting_confirmation", "decisions")
    await db.commit()

    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    change = next(action for action in view["actions"] if action["key"] == "change")
    assert change["label"] == "Send my answers to the agent" and change["input"]["required"] is True
    assert view["actions"][0]["label"] == "Ship it: push and open the pull request"

    empty = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                              json={"action": "change"})
    assert empty.status_code == 422 and empty.json()["detail"]["code"] == "answer_required"

    answer = "The formula rules: fix the worked example. Not in the inventory gives bonus 0."
    changed = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                json={"action": "change", "reason": answer})
    assert changed.status_code == 200, changed.text
    assert changed.json()["run"]["current_node"]["id"] == "work"
    await db.refresh(run)
    assert [item["text"] for item in run.context["po_answers"]] == [answer]
    from app.services.workflow_runs.graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes["work"]
    facts = phase_definition(run, node)["workflow_contract"]["workflow_run_phase"]
    assert facts["product_owner_answers"] == [answer]
    assert "previous_change" not in facts

    from app.services.workflow_runs.phase_contract import MAX_PREVIOUS_PATCH

    patch = "diff --git a/src/api.py b/src/api.py\n+x = 1\ndiff --git a/SPEC.md b/SPEC.md\n+rule\n"
    from app.services.workflow_runs.node_activation import _activate

    run.context = {**dict(run.context or {}), "device_change": {"patch": patch, "node_id": "work"}}
    await _activate(db, run, await graph_for_run(db, run), node, None)
    assert "device_change" not in run.context
    previous = phase_definition(run, node)["workflow_contract"]["workflow_run_phase"]["previous_change"]
    assert previous["files"] == ["src/api.py", "SPEC.md"] and previous["patch"] == patch
    assert "Do not read whole files" in previous["note"]
    run.context = {**dict(run.context or {}), "device_change": {"patch": patch + "+" * MAX_PREVIOUS_PATCH}}
    large = phase_definition(run, node)["workflow_contract"]["workflow_run_phase"]["previous_change"]
    assert "patch" not in large and large["files"] == ["src/api.py", "SPEC.md"] and large["patch_omitted"]


@pytest.mark.asyncio
async def test_the_reviewer_is_asked_for_assumptions_and_the_card_shows_them(db, tmp_path):
    from app.services.workflow_runs.review.runner import run_due_reviews
    from app.services.workflow_runs.review.verdict import ASSUMPTIONS_RULE
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer, changed_repo

    definition = _definition()
    definition["nodes"].insert(2, {"id": "review", "type": "review", "label": "Review",
                                   "config": {"phase": "work", "assumptions": True}})
    definition["nodes"][3]["config"]["shows"] = "review_verdict"
    definition["edges"][1] = {"id": "b", "source_node_id": "work", "target_node_id": "review"}
    definition["edges"].append({"id": "f", "source_node_id": "review", "target_node_id": "decisions"})
    assert validate_phased_definition(definition)["errors"] == []
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), session=session,
                          project_id=workspace_id)
    await db.commit()
    await _turn(db, session.id, ["knowledge_search"])
    question = "A shared Recommended item is packed by every member: intended?"
    reviewer = ScriptedReviewer({"verdict": "pass", "summary": "Fine.", "findings": [], "assumptions": [question]})
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    await db.refresh(run)
    assert ASSUMPTIONS_RULE in reviewer.tasks[0][0]
    assert run.node_state["waiting"]["subject"] == "decisions"
    assert run.node_state["waiting"]["payload"]["output"]["assumptions"] == [question]


@pytest.mark.asyncio
async def test_answers_to_the_readiness_questions_reach_the_build(client, auth_headers, db):
    admin = await admin_user(db)
    key = await publish_phased(db, _definition("readiness"))
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, session=session, project_id=workspace_id)
    resolution = await run_turn_resolution(db, session, user_message="Check it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    await db.commit()
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    assert [action["label"] for action in view["actions"]][:2] == ["Ready: start building",
                                                                 "Answer the questions, then build"]
    change = next(action for action in view["actions"] if action["key"] == "change")
    assert change["input"]["max_length"] == 100_000
    answers = "1. Seed items default seasons to 1-12. " + "2. The server generates the ids. " * 20
    assert len(answers) > 500
    answered = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                 json={"action": "change", "reason": answers})
    assert answered.status_code == 200, answered.text
    await db.refresh(run)
    assert [item["text"] for item in run.context["po_answers"]] == [answers.strip()]


@pytest.mark.asyncio
async def test_the_reviewer_checks_every_product_owner_answer_and_a_spec_review_uses_its_checklist(db, tmp_path):
    from sqlalchemy import select

    from app.models import UsageEvent
    from app.services.workflow_runs.review.runner import run_due_reviews
    from app.services.workflow_runs.review.verdict import (
        ASSUMPTIONS_RULE,
        PO_ANSWERS_RULE,
        SPEC_AUDIT_RULE,
        SPEC_JUDGE_RULE,
        SPEC_REVIEW_RULE,
    )
    from tests.test_workflow_run_pause import _turn
    from tests.workflow_run_review_support import ScriptedReviewer, changed_repo

    definition = _definition()
    definition["nodes"].insert(2, {"id": "review", "type": "review", "label": "Review",
                                   "config": {"phase": "work", "checklist": "spec"}})
    definition["edges"][1] = {"id": "b", "source_node_id": "work", "target_node_id": "review"}
    definition["edges"].append({"id": "f", "source_node_id": "review", "target_node_id": "decisions"})
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(changed_repo(tmp_path / "w"))}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), session=session,
                          project_id=workspace_id)
    run.context = {**dict(run.context or {}), "po_answers": [
        {"text": "A. Add GET /api/trips.\nB. Sort lists by id.", "by": admin.id, "review_attempt": 1},
        {"text": "C. The plan test uses the full inventory.", "by": admin.id, "review_attempt": 2}]}
    await db.commit()
    await _turn(db, session.id, ["knowledge_search"])
    audit = {"audit": [{"check": 2, "file": "SPEC.md", "line": 3, "quote": "ordered by id", "issue": "contradicts"}],
             "answers": [{"answer": 2, "point": "C", "done": False, "evidence": "no inventory in the plan test"}]}
    reviewer = ScriptedReviewer(audit, {"verdict": "changes", "summary": "C missing.", "findings": [
        {"severity": "high", "file": "tests/test_api.py", "line": 1, "fix": "PO answer 2, point C: add it"}]})
    assert await run_due_reviews(db, model_factory=reviewer.factory) == 1
    (first, first_user), (system, user) = reviewer.tasks
    assert SPEC_AUDIT_RULE in first and SPEC_REVIEW_RULE in first and PO_ANSWERS_RULE in first
    assert "PO answer 2:\nC. The plan test" in first_user
    assert SPEC_JUDGE_RULE in system and PO_ANSWERS_RULE in system and ASSUMPTIONS_RULE not in system
    assert "PO answer 1:\nA. Add GET /api/trips." in user and "no inventory in the plan test" in user
    usage = (await db.execute(select(UsageEvent).where(UsageEvent.dispatch_owner == "workflow_run_review"))).scalars()
    assert [(row.tokens_in, row.tokens_out) for row in usage] == [(80, 20)]


def test_spec_writing_interviews_the_product_owner_writes_reviews_with_a_checklist_and_splits_the_stories():
    seed = next(item for item in seed_definitions() if item["key"] == "spec-writing")
    definition = seed["definition"]
    assert validate_phased_definition(definition)["errors"] == []
    graph = parse_phased_definition(definition)
    assert [node.id for node in graph.nodes.values() if node.kind == "phase"] == ["interview", "draft", "split"]
    contract = {node: graph.nodes[node].config["workflow_contract"] for node in ("interview", "draft", "split")}
    assert contract["interview"]["capability_class"] == "read_only" and "Propose an answer" in (
        contract["interview"]["when_to_use"]) and "only question round" in contract["interview"]["when_to_use"]
    assert "design system" in contract["draft"]["when_to_use"] and "living style guide" in (
        contract["split"]["when_to_use"])
    assert contract["draft"]["checks"][0]["params"]["tools"] == ["edit_workspace_file"]
    assert "worked example" in contract["draft"]["when_to_use"] and "product_owner_answers" in (
        contract["draft"]["when_to_use"])
    assert contract["split"]["checks"][0]["params"]["tools"] == ["submit_story_plan"]
    assert graph.nodes["answers"].config == {"decider": "requester", "subject": "interview"}
    assert graph.nodes["spec_review"].config == {"phase": "draft", "checklist": "spec", "assumptions": True}
    assert graph.nodes["decisions"].config["auto_revise"] == 2 and graph.nodes["decisions"].config["tasks"] is False
    routes = {(edge["source_node_id"], edge.get("when")): edge["target_node_id"] for edge in definition["edges"]}
    assert routes[("answers", "changed")] == routes[("answers", "confirmed")] == "draft"
    assert (routes[("decisions", "confirmed")], routes[("decisions", "changed")]) == ("split", "draft")
    assert (routes[("split", None)], routes[("stories", "succeeded")]) == ("stories", "push")


@pytest.mark.asyncio
async def test_an_answer_lands_on_the_platform_work_item_as_a_note(client, auth_headers, db):
    from app.models.runtime.secure_work import WorkItem

    admin = await admin_user(db)
    item = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-77", title="Spec it",
                    work_state="intake")
    db.add(item)
    await db.flush()
    key = await publish_phased(db, _definition("interview"))
    workspace_id = await run_workspace(db, admin, item.id)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, session=session, project_id=workspace_id,
                          work_item_id=item.id)
    resolution = await run_turn_resolution(db, session, user_message="Ask.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    await db.commit()
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    assert [action["label"] for action in view["actions"]][:2] == ["Write the spec with the proposed answers",
                                                                 "Answer the questions, then write"]
    answer = "1. Offline only. " + "2. Weights in grams. " * 120
    answered = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                 json={"action": "change", "reason": answer})
    assert answered.status_code == 200, answered.text
    await db.refresh(item)
    note = item.source_fields_json["platform_notes"][-1]["note"]
    assert note.startswith(f"Product owner answer (spec questions, workflow run {run.id}):") and note.endswith(
        answer.strip())


@pytest.mark.asyncio
async def test_accepting_all_proposals_is_an_answer_the_next_phase_and_the_spec_review_see(client, auth_headers, db):
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.po_answers import ACCEPTED_PREFIX
    from app.services.workflow_runs.review.verdict import SPEC_DECISIONS_RULE

    admin = await admin_user(db)
    key = await publish_phased(db, _definition("readiness"))
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, session=session, project_id=workspace_id)
    resolution = await run_turn_resolution(db, session, user_message="Check it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    await db.commit()
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    confirm = next(action for action in view["actions"] if action["key"] == "confirm")
    accepted = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                 json={"action": "confirm", "payload_hash": confirm.get("payload_hash") or
                                       run.node_state["waiting"].get("payload_hash")})
    assert accepted.status_code == 200, accepted.text
    await db.refresh(run)
    [answer] = [item["text"] for item in run.context["po_answers"]]
    assert answer == f"{ACCEPTED_PREFIX}Done."
    node = next(node for node in (await graph_for_run(db, run)).nodes.values()
                if node.kind == "phase" and node.id != "readiness")
    facts = phase_definition(run, node)["workflow_contract"]["workflow_run_phase"]
    assert facts["product_owner_answers"] == [answer]
    assert "Decisions section" in SPEC_DECISIONS_RULE and '"high"' in SPEC_DECISIONS_RULE
