"""DevOps workflows S3: human-in-the-loop nodes of a phased run.

A conversation is a clarification bound to the run, a confirmation decides on the hash of a typed payload (the
test contract is the Work item's change plan behind the coverage gate), and an approval is four-eyes under the
platform approval rule.
"""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Approval, ClarificationQuestion, WorkflowRunDecision
from app.models.runtime.secure_work import WorkChangePlan, WorkItem
from app.services.approval.resolution_service import decide_pending_approval
from app.services.governance.approval_rule import set_approval_rule
from app.services.inbox.service import personal_inbox
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.sweep import sweep_waiting_runs
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace
from tests.prompt_catalog_publish_support import second_admin


def _definition(hitl: dict, routes: list[tuple[str, str, str | None]]) -> dict:
    """start → <hitl node> → (routes) …, with a phase and two outcomes to route to."""
    return {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start"},
            hitl,
            {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
            {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}},
        ],
        "edges": [
            {"id": "e0", "source_node_id": "start", "target_node_id": hitl["id"]},
            *[{"id": f"r{index}", "source_node_id": hitl["id"], "target_node_id": target,
               **({"when": when} if when else {})} for index, (when, target, _) in enumerate(routes)],
            {"id": "w1", "source_node_id": "work", "target_node_id": "done"},
        ],
    }


async def _start(db, definition: dict, *, work_item_id: str | None = None):
    admin = await admin_user(db)
    key = await publish_phased(db, definition)
    workspace_id = await run_workspace(db, admin, work_item_id)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, session=session, work_item_id=work_item_id,
                          project_id=workspace_id)
    return admin, run, session


@pytest.mark.asyncio
async def test_a_conversation_asks_in_the_thread_and_the_reply_continues_the_run(db):
    node = {"id": "ask", "type": "user_conversation", "label": "Scope",
            "config": {"question": "Which component does the change touch?"}}
    admin, run, session = await _start(db, _definition(node, [(None, "work", None)]))
    assert (run.status, run.waiting_kind) == ("waiting", "waiting_for_reply")
    question = await db.get(ClarificationQuestion, run.node_state["waiting"]["clarification_id"])
    assert (question.status, question.session_id, question.question_text) == (
        "open", session.id, "Which component does the change touch?")
    assert any(item["kind"] == "clarification" for item in (await personal_inbox(db, admin))["waiting"])

    resolution = await run_turn_resolution(db, session, user_message="The billing service.")
    assert resolution["workflow_run"]["node_id"] == "work"  # the reply's own turn runs the next phase
    assert run.context["replies"]["ask"] == "The billing service."
    assert question.status == "answered"


async def _item(db) -> WorkItem:
    item = WorkItem(source_type="jira", source_instance="test", source_key=f"TC-{uuid.uuid4().hex[:6]}",
                    title="Totals are wrong")
    db.add(item)
    await db.flush()
    return item


CONTRACT = {"id": "contract", "type": "user_confirmation", "label": "Test contract",
            "config": {"subject": "test_contract"}}
CONFIRM_ROUTES = [("confirmed", "work", None), ("changed", "blocked", None), ("stopped", "blocked", None)]
# A read-only phase that submits the test contract, so the run drafts the plan the confirmation shows.
CLARIFY = copy.deepcopy(PHASE)
CLARIFY["output"] = "test_contract"
CLARIFY["tool_policy"]["allowlist"].append("submit_test_contract")
CLARIFY["workflow_contract"]["checks"].append({"type": "tool_called", "params": {"tools": ["submit_test_contract"]},
                                               "blocking": True, "description": "The test contract was submitted"})
CRITERIA = [{"id": "AC1", "text": "Totals round half up", "tests": ["tests/test_billing.py::test_totals"],
             "command": "pytest tests/test_billing.py"}]


def contract_definition(routes: list[tuple[str, str, str | None]] = CONFIRM_ROUTES) -> dict:
    """start → clarify (submits the test contract) → draft the change plan → confirm it → (routes) …"""
    definition = _definition(CONTRACT, routes)
    definition["nodes"][1:1] = [
        {"id": "clarify", "type": "phase", "label": "Clarify", "config": copy.deepcopy(CLARIFY)},
        {"id": "draft", "type": "platform_action", "label": "Draft", "config": {"action": "work.draft_change_plan"}},
    ]
    definition["edges"][0] = {"id": "e0", "source_node_id": "start", "target_node_id": "clarify"}
    definition["edges"] += [
        {"id": "c1", "source_node_id": "clarify", "target_node_id": "draft"},
        {"id": "c2", "source_node_id": "draft", "target_node_id": "contract", "when": "succeeded"},
        {"id": "c3", "source_node_id": "draft", "target_node_id": "blocked", "when": "failed"},
    ]
    return definition


async def reach_contract(db, run, session, criteria: list[dict] | None = None) -> None:
    """Clarify submits the contract and passes; the server drafts the plan and the run waits for the confirmation."""
    from app.services.workflow_runs.phase_outputs import submit_output

    answer = await submit_output(db, run, "submit_test_contract", {"criteria": criteria or CRITERIA})
    assert answer["state"] == "recorded", answer
    resolution = await run_turn_resolution(db, session, user_message="Clarify.")
    await phase_turn(db, session.id, resolution, ["knowledge_search", "submit_test_contract"])
    assert (run.current_node_id, run.waiting_kind) == ("contract", "awaiting_confirmation"), run.current_node_id


async def drafted_plan(db, run) -> WorkChangePlan:
    return await db.get(WorkChangePlan, run.context["change_plan"]["id"])


@pytest.mark.asyncio
async def test_confirming_the_test_contract_approves_the_change_plan_bound_to_its_payload_hash(client, auth_headers, db):
    item = await _item(db)
    _admin, run, session = await _start(db, contract_definition(), work_item_id=item.id)
    await reach_contract(db, run, session)
    plan = await drafted_plan(db, run)
    assert (plan.created_by, plan.evidence_json["workflow_run_id"]) == (run.requested_by, run.id)
    assert plan.acceptance_criteria_json[0]["tests"] == ["tests/test_billing.py::test_totals"]
    await db.commit()
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    waiting = view["waiting"]
    assert waiting["subject"] == "test_contract" and waiting["payload"]["blockers"] == []
    assert (waiting["payload"]["change_plan_id"], waiting["payload"]["plan_hash"]) == (
        plan.id, run.context["change_plan"]["hash"])  # exactly the plan the run drafted
    assert [action["key"] for action in view["actions"]][:3] == ["confirm", "change", "stop"]
    assert view["actions"][0]["label"] == "Confirm these tests"

    stale = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                              json={"action": "confirm", "payload_hash": "sha256:other"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "payload_changed"
    confirmed = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                  json={"action": "confirm", "payload_hash": waiting["payload_hash"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["run"]["current_node"]["id"] == "work"
    await db.refresh(plan)
    assert plan.status == "approved"
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id))).scalar_one()
    assert (decision.kind, decision.action, decision.payload_hash) == (
        "confirmation", "confirmed", waiting["payload_hash"])


@pytest.mark.asyncio
async def test_an_uncovered_test_contract_cannot_be_confirmed_only_changed(client, auth_headers, db):
    item = await _item(db)
    _admin, run, session = await _start(db, contract_definition(), work_item_id=item.id)
    await reach_contract(db, run, session)
    # Edited in Work while the run waits: AC1 loses its command. The decision rebuilds the payload.
    plan = await drafted_plan(db, run)
    plan.acceptance_criteria_json = [{**plan.acceptance_criteria_json[0], "validation_commands": []}]
    await db.commit()
    stale = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                              json={"action": "confirm", "payload_hash": run.node_state["waiting"]["payload_hash"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "payload_changed"
    view = (await client.get(f"/api/v1/workflow-runs/{run.id}", headers=auth_headers)).json()["run"]
    assert "AC1" in view["waiting"]["payload"]["blockers"][0]
    assert "confirm" not in {action["key"] for action in view["actions"]}
    refused = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                json={"action": "confirm", "payload_hash": view["waiting"]["payload_hash"]})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "nothing_to_confirm"
    changed = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                json={"action": "change"})
    assert changed.json()["run"]["outcome"] == "blocked"


@pytest.mark.asyncio
async def test_an_approval_is_four_eyes_unless_the_platform_rule_is_single_admin(db):
    node = {"id": "approve", "type": "approval", "label": "Deploy", "config": {"unlocks": "The deploy job."}}
    routes = [("approved", "work", None), ("rejected", "blocked", None)]
    admin, run, _session = await _start(db, _definition(node, routes))
    approval = await db.get(Approval, run.node_state["waiting"]["approval_id"])
    assert (approval.status, approval.requested_by, approval.action.startswith("workflow_run.approval")) == (
        "pending", admin.id, True)
    from app.services.workflow_runs.actions import available_actions, perform_action
    from app.services.workflow_runs.records import WorkflowRunError

    assert "approve" not in {item["key"] for item in await available_actions(db, run, access="write", user=admin)}
    with pytest.raises(WorkflowRunError) as refused:
        await perform_action(db, run, user=admin, body={"action": "approve"})
    assert refused.value.code == "four_eyes"
    reviewer = await second_admin(db)
    inbox = await personal_inbox(db, reviewer)
    assert any(item["kind"] == "workflow_run_approval" and item["id"] == run.id for item in inbox["waiting"])
    assert not any(item.get("id") == approval.id for item in inbox["waiting"])  # not twice as a review
    await perform_action(db, run, user=reviewer, body={"action": "approve"})
    assert (run.status, run.current_node_id, approval.status) == ("running", "work", "approved")

    # Single-admin rule: the requester approves their own run; a decision made elsewhere moves the run too.
    await set_approval_rule(db, rule="single_admin", actor_id=admin.id)
    _admin, second, _session = await _start(db, _definition(node, routes))
    assert "approve" in {item["key"] for item in await available_actions(db, second, access="write", user=admin)}
    await decide_pending_approval(db, approval_id=second.node_state["waiting"]["approval_id"],
                                  resolved_by=admin.id, status="rejected")
    assert (second.status, second.outcome) == ("completed", "blocked")


@pytest.mark.asyncio
async def test_an_expired_approval_and_an_unanswered_question_pause_the_run(db):
    node = {"id": "approve", "type": "approval", "label": "Deploy"}
    admin, run, _session = await _start(db, _definition(node, [("approved", "work", None),
                                                               ("rejected", "blocked", None)]))
    first_approval = run.node_state["waiting"]["approval_id"]
    await decide_pending_approval(db, approval_id=first_approval, resolved_by=None, status="expired")
    assert (run.status, run.pause_reason) == ("paused", "approval_timeout")
    from app.services.workflow_runs.pause import continue_run

    await continue_run(db, run, user=admin, k=1, is_admin=True)
    assert run.waiting_kind == "awaiting_approval"
    assert run.node_state["waiting"]["approval_id"] != first_approval  # a new request

    ask = {"id": "ask", "type": "user_conversation", "config": {"question": "Which one?", "timeout_hours": 2,
                                                                "reminder_hours": 1}}
    _admin, waiting, _session = await _start(db, _definition(ask, [(None, "work", None)]))
    await sweep_waiting_runs(db, now=utc_now() + timedelta(minutes=90))
    assert waiting.status == "waiting" and waiting.node_state["waiting"]["reminded_at"]
    await sweep_waiting_runs(db, now=utc_now() + timedelta(hours=3))
    assert (waiting.status, waiting.pause_reason) == ("paused", "no_reply")
    await continue_run(db, waiting, user=admin, k=1, is_admin=True)
    assert (waiting.status, waiting.waiting_kind) == ("waiting", "waiting_for_reply")


@pytest.mark.asyncio
async def test_a_drafted_ticket_is_confirmed_on_the_phase_answer_it_shows(db):
    admin = await admin_user(db)
    definition = {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "draft", "type": "phase", "label": "Draft", "config": copy.deepcopy(PHASE)},
            {"id": "ticket", "type": "user_confirmation", "config": {"subject": "ticket_draft"}},
            {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
            {"id": "stop", "type": "outcome", "config": {"outcome": "stopped"}},
        ],
        "edges": [
            {"id": "a", "source_node_id": "start", "target_node_id": "draft"},
            {"id": "b", "source_node_id": "draft", "target_node_id": "ticket"},
            {"id": "c", "source_node_id": "ticket", "target_node_id": "done", "when": "confirmed"},
            {"id": "d", "source_node_id": "ticket", "target_node_id": "draft", "when": "changed", "kind": "loop",
             "max_iterations": 2},
            {"id": "e", "source_node_id": "ticket", "target_node_id": "stop", "when": "stopped"},
        ],
    }
    key = await publish_phased(db, definition)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, session=session, project_id=workspace_id)
    resolution = await run_turn_resolution(db, session, user_message="Draft it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])
    assert run.waiting_kind == "awaiting_confirmation"
    assert run.node_state["waiting"]["payload"] == {"subject": "ticket_draft", "text": "Done."}
