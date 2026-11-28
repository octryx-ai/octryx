"""Platform actions run on the server within the phase class and once per pass, only a person who may act attaches a session, and an octryx session runs Workflow C's fix phase end to end without editing the confirmed test."""

from __future__ import annotations

import pytest

from app.models import WorkflowRun
from app.services.devices.job_offer import offer_body
from app.services.mcp_governed_knowledge import McpCaller
from app.services.mcp_workflow_run_tools import mcp_workflow_action_request, mcp_workflow_run_status
from app.services.mcp_workflow_tools import mcp_workflow_select
from app.services.workflow_runs.records import active_run_for_session
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture
from tests.workflow_run_octryx_support import (  # noqa: F401
    CONFIRMED,
    _bound_run,
    _call,
    _hook,
    _launcher,
    _server_pipeline,
)

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_platform_actions_run_on_the_server_within_the_phase_class_and_once_per_pass(db, monkeypatch):
    from tests.test_workflow_run_platform_actions import FakeTools

    tools = FakeTools(monkeypatch, {"list_github_action_runs": [{"workflow_runs": []}]})
    run, gateway, key, workspace_id = await _bound_run(db)
    run.repository, run.branch = "github:acme/pay", "bugfix/X-1-fix"
    admin = await admin_user(db)
    caller = McpCaller(user_id=admin.id, grant_id="mcp", scopes=("workflow:read", "workflow:execute"),
                       workspace_header=workspace_id, session_key=key)
    args = {"caller": caller, "user": admin, "workspace_id": workspace_id}
    denied = await mcp_workflow_action_request(db, **args, arguments={"action": "jira.comment",
                                                                      "params": {"text_from": "findings"}})
    assert (denied["state"], denied["reason"]) == ("denied", "phase_class_too_low")
    raw = await mcp_workflow_action_request(db, **args, arguments={"action": "jira.transition",
                                                                   "params": {"status": "Done"}})
    assert raw["state"] == "invalid_request"  # never a raw Jira status
    first = await mcp_workflow_action_request(db, **args, arguments={"action": "ci.status", "params": {}})
    again = await mcp_workflow_action_request(db, **args, arguments={"action": "ci.status", "params": {}})
    assert first["state"] in ("running", "failed", "succeeded") and again["replayed"] is True
    assert tools.tools() == ["list_github_action_runs"]
    status = await mcp_workflow_run_status(db, **args, arguments={"detail": True})  # the whole contract
    assert status["workflow_run"]["run"]["id"] == run.id
    assert status["workflow_run"]["work_item"] is None  # this run has no Work item
    from app.models.runtime.secure_work import WorkItem

    item = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-28", title="T11: templates",
                    description="Acceptance Criteria:\n1. SQLite table trip_templates exists.", project_id=workspace_id)
    db.add(item)
    await db.flush()
    run.work_item_id = item.id
    with_item = (await mcp_workflow_run_status(db, **args, arguments={}))["workflow_run"]["work_item"]
    assert with_item["key"] == "OCX-28" and "trip_templates exists" in with_item["description"]
    # A model may pass the workflow key as the run id; the session's own run answers, with a note.
    keyed = await mcp_workflow_run_status(db, **args, arguments={"run_id": "ticket-delivery"})
    assert keyed["workflow_run"]["run"]["id"] == run.id and run.id in keyed["note"]
    stranger = McpCaller(user_id=admin.id, grant_id="mcp", scopes=("workflow:read",), workspace_header=workspace_id,
                         session_key=None)
    unbound = await mcp_workflow_run_status(db, caller=stranger, user=admin, workspace_id=workspace_id,
                                            arguments={"run_id": "ticket-delivery"})
    assert (unbound["state"], unbound["reason"]) == ("not_found", "unknown_run")


@pytest.mark.asyncio
async def test_only_a_person_who_may_act_attaches_and_a_new_run_waits_for_the_users_confirmation(db):
    from app.models.runtime.secure_work import WorkItem
    from app.services.session.approval_decision import decide_session_approval

    run, _gateway, _key, workspace_id = await _bound_run(db)
    member = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="member"))
    other, other_key = await _launcher(db, member, workspace_id)
    caller = McpCaller(user_id=member.id, grant_id="mcp", scopes=("workflow:read",), workspace_header=workspace_id,
                       session_key=other_key)
    refused = await mcp_workflow_select(db, caller=caller, user=member, workspace_id=workspace_id,
                                        arguments={"run_id": run.id})
    assert refused["reason"] == "run_read_only" and await active_run_for_session(db, other.id) is None
    foreign = await mcp_workflow_select(db, caller=caller, user=member, workspace_id=await seed_workspace(db),
                                        arguments={"run_id": run.id})
    assert foreign["state"] in ("not_found", "needs_configuration")
    assert offer_body(type("Job", (), {"id": "j", "turn_id": "t", "turn_prompt": "", "folder": "/f",
                                       "profile": "governed", "turn_model": "", "workspace_id": workspace_id,
                                       "session_id": "s", "claude_session_id": None, "resume_claude_session_id": None,
                                       "policy_decision_id": None})(), limits={},
                      workflow_run_id=run.id)["workflow_run_id"] == run.id

    item = WorkItem(source_type="jira", source_instance="t", source_key="PAY-41", title="x", project_id=workspace_id)
    db.add(item)
    await db.flush()
    key_of_flow = (await db.get(WorkflowRun, run.id)).workflow_key
    pending = await mcp_workflow_select(db, caller=caller, user=member, workspace_id=workspace_id,
                                        arguments={"workflow_key": key_of_flow, "work_item": "PAY-41"})
    assert pending["state"] == "needs_confirmation" and await active_run_for_session(db, other.id) is None
    await decide_session_approval(db, approval_id=pending["approval_id"], decider_id=member.id, decision="approved",
                                  reason=None)
    started = await mcp_workflow_select(db, caller=caller, user=member, workspace_id=workspace_id,
                                        arguments={"workflow_key": key_of_flow, "work_item": "PAY-41"})
    assert started["state"] == "selected"
    assert (await active_run_for_session(db, other.id)).work_item_id == item.id


# --- end to end: Workflow C's fix phase in a simulated octryx-claude session ----------------------------------------


