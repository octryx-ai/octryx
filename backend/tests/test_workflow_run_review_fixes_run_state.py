"""Run state stays consistent under review fixes: decisions re-read the run, platform actions run once per pass, budgets and plan changes are bounded, sub-workflows nest safely and paused runs continue with a new turn."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from app.models import Approval, User, WorkflowRun, WorkflowRunDecision
from app.services.approval.resolution_service import decide_pending_approval
from app.services.workflow_runs.access import require_run
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.approvals import on_approval_decided
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.graph import graph_for_run
from app.services.workflow_runs.limits import pause_run, set_loop_ceiling
from app.services.workflow_runs.pause import change_plan, continue_run
from app.services.workflow_runs.platform_actions import run_platform_action
from app.services.workflow_runs.records import WorkflowRunError, main_session_id, new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, phase_turn, phased_definition, publish_phased, run_workspace
from tests.policy_engine_support import make_user
from tests.test_workflow_run_hitl import CONFIRM_ROUTES, contract_definition, drafted_plan, reach_contract
from tests.test_workflow_run_hitl import _definition as hitl_definition
from tests.test_workflow_run_platform_actions import FakeTools
from tests.test_workflow_run_platform_actions import _definition as action_definition
from tests.workflow_run_review_fixes_support import _item


def _calls(child_key: str) -> dict:
    return {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "sub", "type": "sub_workflow", "label": "Child", "config": {"workflow_key": child_key}},
                  {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
                  {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
        "edges": [{"id": "a", "source_node_id": "start", "target_node_id": "sub"},
                  {"id": "b", "source_node_id": "sub", "target_node_id": "done", "when": "done"},
                  {"id": "c", "source_node_id": "sub", "target_node_id": "blocked", "when": "blocked"}],
    }


@pytest.mark.asyncio
async def test_a_changed_payload_is_rebuilt_at_decision_time_and_the_decision_hashes_the_taken_over_criteria(db):
    """Finding 6: the drafted plan changed while the run waits refreshes the payload; confirm needs the new one."""
    admin = await admin_user(db)
    item = await _item(db, None)
    key = await publish_phased(db, contract_definition())
    workspace_id = await run_workspace(db, admin, item.id)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=key, work_item_id=item.id, session=session,
                          project_id=workspace_id)
    await reach_contract(db, run, session)
    seen = run.node_state["waiting"]["payload_hash"]
    second = await drafted_plan(db, run)
    second.acceptance_criteria_json = [*second.acceptance_criteria_json,
                                       {"id": "AC2", "text": "Fees stay", "validation_commands": ["pytest tests/test_billing.py"]}]
    await db.flush()

    with pytest.raises(WorkflowRunError) as changed:
        await perform_action(db, run, user=admin, body={"action": "confirm", "payload_hash": seen})
    assert (changed.value.code, changed.value.persist) == ("payload_changed", True)
    waiting = run.node_state["waiting"]
    assert waiting["payload"]["change_plan_id"] == second.id and waiting["payload_hash"] != seen

    await perform_action(db, run, user=admin, body={"action": "confirm", "payload_hash": waiting["payload_hash"],
                                                    "human_verified_criteria": ["AC1"]})
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id))).scalar_one()
    assert decision.payload["human_verified_criteria"] == ["AC1"]
    assert decision.payload_hash != waiting["payload_hash"]
    assert second.status == "approved"


@pytest.mark.asyncio
async def test_a_second_decision_re_reads_the_run_and_a_stale_turn_report_changes_nothing(db):
    """Finding 3: whoever comes second decides against the current state; an old pass never reports."""
    admin = await admin_user(db)
    advance = {"id": "go", "type": "user_confirmation", "label": "Go", "config": {"subject": "advance"}}
    key = await publish_phased(db, hitl_definition(advance, CONFIRM_ROUTES))
    workspace_id = await run_workspace(db, admin)
    run = await start_run(db, user=admin, workflow_key=key,
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    hash_seen = run.node_state["waiting"]["payload_hash"]
    await db.flush()
    # Another transaction stopped the run and committed meanwhile; this session still holds the old copy.
    await db.execute(update(WorkflowRun).where(WorkflowRun.id == run.id).values(
        status="stopped", outcome="stopped", state_version=WorkflowRun.state_version + 1,
    ).execution_options(synchronize_session=False))
    assert run.status == "waiting"

    locked = await require_run(db, run.id, admin, write=True)
    assert locked.status == "stopped"  # re-read on claim
    with pytest.raises(WorkflowRunError) as late:
        await perform_action(db, locked, user=admin, body={"action": "confirm", "payload_hash": hash_seen})
    assert late.value.code == "not_awaiting_confirmation"

    loop_key = await publish_phased(db, phased_definition(max_iterations=2))
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    looping = await start_run(db, user=admin, workflow_key=loop_key, project_id=workspace_id, session=session)
    old_pass = await run_turn_resolution(db, session, user_message="Go.")
    await phase_turn(db, session.id, old_pass, ["knowledge_search"])  # the gate fails: work is entered again
    assert (looping.current_node_id, looping.status) == ("work", "running")
    entry = looping.node_state["entry"]
    await phase_turn(db, session.id, old_pass, ["knowledge_search", "knowledge_read"])  # reported late
    assert (looping.status, looping.node_state["entry"]) == ("running", entry)


@pytest.mark.asyncio
async def test_a_platform_action_runs_once_per_pass_and_a_repeated_approval_hook_never_reruns_it(db, monkeypatch):
    """Part-2 re-check: idempotency key per pass; the approval hook acts once."""
    admin = await admin_user(db)
    approval = Approval(requested_by=admin.id, action="Approve tool execution for add_jira_comment", status="pending")
    db.add(approval)
    await db.flush()
    tools = FakeTools(monkeypatch, {"add_jira_comment": [
        {"approval_required": True, "approval_id": approval.id, "approval_status": "pending"},
        {"status": "created"},
    ]})
    item = await _item(db, None)
    key = await publish_phased(db, action_definition("jira.comment", {"text_from": "work_item"}))
    workspace_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, work_item_id=item.id,
                          session=await new_chat_session(db, admin, workspace_id))
    approval.session_id = await main_session_id(db, run)  # a chat tool approval of the run's session
    await decide_pending_approval(db, approval_id=approval.id, resolved_by=admin.id, status="approved")
    await on_approval_decided(db, approval)  # delivered twice
    assert (run.status, tools.tools()) == ("completed", ["add_jira_comment", "add_jira_comment"])

    node = (await graph_for_run(db, run)).nodes["act"]
    run.current_node_id, run.node_state = "act", {"node_id": "act", "entry": 2}  # the action's pass, replayed
    assert await run_platform_action(db, run, node) == "succeeded"
    assert tools.tools() == ["add_jira_comment", "add_jira_comment"]


@pytest.mark.asyncio
async def test_budget_overrides_are_clamped_and_plan_changes_are_bounded(db):
    """Findings 5 and 8: an override never exceeds the ceiling; only an admin goes past a ceiling-less key;
    the plan changes at most the loop ceiling's times."""
    admin = await admin_user(db)
    requester = await db.get(User, await make_user(db, admin=False))
    definition = {**phased_definition(max_iterations=1), "budget": {"tool_calls": 10}}
    key = await publish_phased(db, definition)
    item = await _item(db, None, run_limits={"budget": {"tool_calls": 100, "tokens": 5000}})
    workspace_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, work_item_id=item.id)
    assert run.limits["budget"] == {"tool_calls": 30, "tokens": 5000}
    assert run.limits["budget_ceiling"] == {"tool_calls": 30}

    await pause_run(db, run, reason="budget_limit", actor_id=None, detail={"keys": ["tokens"],
                                                                            "resume": {"kind": "stay"}})
    with pytest.raises(WorkflowRunError) as beyond:
        await continue_run(db, run, user=requester, k=1, is_admin=False)
    assert beyond.value.code == "beyond_budget_ceiling"
    await continue_run(db, run, user=admin, k=1, is_admin=True)
    assert run.limits["budget"]["tokens"] == 10000

    await set_loop_ceiling(db, 1, user_id=admin.id)
    await pause_run(db, run, reason="loop_limit", actor_id=None, detail={"edge_id": "rework"})
    await change_plan(db, run, user=requester)
    assert (run.status, run.current_node_id, run.context["plan_changes"]) == ("running", "work", 1)
    await pause_run(db, run, reason="loop_limit", actor_id=None, detail={"edge_id": "rework"})
    with pytest.raises(WorkflowRunError) as limit:
        await change_plan(db, run, user=requester)
    assert limit.value.code == "plan_change_limit"
    await change_plan(db, run, user=admin, is_admin=True)


@pytest.mark.asyncio
async def test_sub_workflows_never_start_themselves_and_a_finished_child_leaves_no_stale_link(db):
    """Finding 9."""
    admin = await admin_user(db)
    own = f"self-{uuid.uuid4().hex[:6]}"
    await publish_phased(db, _calls(own), key=own)
    workspace_id = await run_workspace(db, admin)
    looping = await start_run(db, user=admin, workflow_key=own, project_id=workspace_id)
    assert looping.status == "failed" and "start itself" in looping.last_error

    child = await publish_phased(db, {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"}, {"id": "end", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "x", "source_node_id": "start", "target_node_id": "end"}],
    })
    workspace_id = await run_workspace(db, admin)
    parent = await start_run(db, user=admin, workflow_key=await publish_phased(db, _calls(child)),
                             project_id=workspace_id)
    assert (parent.status, parent.outcome, parent.current_node_id) == ("completed", "done", "done")
    assert "child_run_id" not in parent.node_state


@pytest.mark.asyncio
async def test_continuing_after_a_budget_pause_in_a_phase_starts_a_new_turn(db, monkeypatch):
    """Continued after budget_limit, the device runs must not stand "running" in their fix phase: the budget has
    stopped the phase's sessions and "stay" alone only sets the status."""
    import app.services.workflow_runs.engine as engine

    admin = await admin_user(db)
    key = await publish_phased(db, {**phased_definition(max_iterations=1), "budget": {"tokens": 10}})
    item = await _item(db, None)
    workspace_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, work_item_id=item.id)
    entered = []

    async def restart_at(_db, run_, node_id, *, actor_id):
        entered.append(node_id)
        run_.status = "running"

    monkeypatch.setattr(engine, "restart_at", restart_at)
    await pause_run(db, run, reason="budget_limit", actor_id=None, detail={"keys": ["tokens"],
                                                                            "resume": {"kind": "stay"}})
    await continue_run(db, run, user=admin, k=1, is_admin=True)
    assert entered == [run.current_node_id] and run.status == "running"


@pytest.mark.asyncio
async def test_a_run_action_with_an_unknown_field_is_refused(client, auth_headers):
    """A continue that sends its hint as "note" (the field is "reason") is not silently dropped."""
    refused = await client.post("/api/v1/workflow-runs/no-such-run/actions", headers=auth_headers,
                                json={"action": "continue", "k": 2, "note": "put it into its own module"})
    assert refused.status_code == 422 and "note" in refused.text


@pytest.mark.asyncio
async def test_change_plan_hands_the_persons_reason_to_the_re_entered_phase(db):
    """Back to reproduce to correct an existing test that asserted the bug; the reason
    must reach the phase (po_answers), as it does for continue."""
    admin = await admin_user(db)
    key = await publish_phased(db, phased_definition(max_iterations=1))
    item = await _item(db, None)
    workspace_id = await run_workspace(db, admin, item.id)
    run = await start_run(db, user=admin, workflow_key=key, project_id=workspace_id, work_item_id=item.id)
    await pause_run(db, run, reason="runtime_failed", actor_id=None, detail={"resume": {"kind": "restart"}})
    reason = "brew_form_test.dart:176 asserts the bug ('1.0'): change it to '15.0' and name it in the reproduction."
    await perform_action(db, run, user=admin, body={"action": "change_plan", "reason": reason})
    assert [item["text"] for item in run.context["po_answers"]] == [reason]
