"""Typed graph lifecycle integration; only the ordinary permissions callback is substituted."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.models import (
    FlowDefinitionVersion,
    Session,
    WorkflowRun,
    WorkflowRunEvent,
)
from app.models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse
from app.models.security.user import UserProject
from app.services.workflow_runs import engine, phase_turns, records, sub_workflows
from app.services.workflow_runs.graph import PhasedNode
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.handoff import allocation, lifecycle, owner_lifecycle, permissions, service
from app.services.workflow_runs.phase_outputs import submit_output
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.team_handoff_support import action, counts, rights, setup_case

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("scripted_pool")]


@pytest.fixture(autouse=True)
async def permission_seam(db, monkeypatch):
    connection = await db.connection()
    await connection.run_sync(lambda bind: [table.create(bind, checkfirst=True) for table in
        (WorkflowHandoff.__table__, WorkflowHandoffResponse.__table__)])
    monkeypatch.setattr(permissions, "rights_evaluator", rights)
    monkeypatch.setattr(allocation, "rights_evaluator", rights)


def edge(name, source, target, when=None):
    return {"id": name, "source_node_id": source, "target_node_id": target, **({"when": when} if when else {})}


async def graph_case(db, *, detached=False, legacy=False):
    c = await setup_case(db, pool=True, detach=detached)
    contract, child_descriptor = c.row.contract, c.row.child_descriptor
    await db.delete(c.row)
    await db.flush()
    child_version = await db.get(FlowDefinitionVersion, child_descriptor["version_id"])
    child_version.definition_json = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "read", "type": "phase", "config": {"agent": "assistant", "output": "definition_of_ready",
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request", "workflow_contract": {"capability_class": "read_only",
                "workflow_id": "knowledge_request", "workflow_class": "knowledge_request",
                "checks": [{"type": "tool_called", "params": {"tools": ["submit_definition_of_ready"]},
                            "blocking": True, "description": "The received task was submitted"}]},
            "tool_policy": {"allowlist": ["submit_definition_of_ready"], "denylist": []}}},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [edge("start-read", "start", "read"), edge("read-done", "read", "done")]}
    validation = validate_phased_definition(child_version.definition_json)
    assert validation["valid"], validation
    node_config = {"workflow_key": child_descriptor["workflow_key"],
                   "handoff": ["definition_of_ready"] if legacy else contract}
    parent_version = await db.get(FlowDefinitionVersion, c.parent.flow_definition_version_id)
    parent_version.definition_json = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "draft", "type": "phase", "config": child_version.definition_json["nodes"][1]["config"]},
        {"id": "confirm", "type": "user_confirmation", "config": {
            "subject": "advance", "shows": "definition_of_ready"}},
        {"id": "offer", "type": "sub_workflow", "config": node_config},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
        {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
        "edges": [edge("start-draft", "start", "draft"), edge("draft-confirm", "draft", "confirm"),
                  edge("confirm-offer", "confirm", "offer", "confirmed"),
                  edge("offer-done", "offer", "done", "done"),
                  edge("offer-blocked", "offer", "blocked", "blocked")]}
    validation = validate_phased_definition(parent_version.definition_json)
    assert validation["valid"], validation
    c.parent.status, c.parent.waiting_kind = "running", None
    c.original_session = Session(user_id=c.sender.id, project_id=c.parent.project_id)
    db.add(c.original_session)
    await db.flush()
    await records.bind_session(db, c.parent, c.original_session, actor_id=c.sender.id)
    before = await counts(db)
    await sub_workflows.start_sub_workflow(db, c.parent,
        PhasedNode("offer", "sub_workflow", "Controlled handoff", node_config), actor_id=c.sender.id)
    if not legacy:
        c.row = (await db.execute(select(WorkflowHandoff).where(
            WorkflowHandoff.parent_run_id == c.parent.id))).scalar_one()
        assert await counts(db) == before
        assert c.row.child_run_id is None and c.row.receiver_session_id is None
    await db.commit()
    return c


async def accepted(db, c):
    binding = await service.accept_handoff(db, c.row.id, c.p, action(c.row),
        rights_evaluator=permissions.rights_evaluator, allocator=allocation.allocate_child)
    await db.commit()  # production lifecycle must initialize only after this commit
    return binding, await db.get(WorkflowRun, binding["child_run_id"])


async def started(db, c):
    binding, child = await accepted(db, c)
    result = await lifecycle.start_accepted_child(db, binding)
    assert result["state"] == "started"
    return binding, child


async def test_typed_offer_dormant_then_post_commit_start_once_real_published_phase(db):
    c = await graph_case(db)
    binding, child = await accepted(db, c)
    assert child.current_node_id is None and child.waiting_kind == allocation.PENDING_COMMIT
    assert await records.main_session_id(db, child) == binding["receiver_session_id"]
    await lifecycle.start_accepted_child(db, binding)
    await lifecycle.start_accepted_child(db, binding)
    assert (child.status, child.current_node_id) == ("running", "read")
    from app.services.workflow_runs.phase_contract import phase_definition
    from app.services.workflow_runs.phase_marker import RUN_PHASE_CONTRACT_KEY
    graph = await engine.graph_for_run(db, child)
    phase = phase_definition(child, graph.nodes["read"])
    assert phase["workflow_contract"][RUN_PHASE_CONTRACT_KEY]["inputs"] == {
        "definition_of_ready": c.row.envelopes["definition_of_ready"]["envelope"]["record"]}
    starts = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == child.id, WorkflowRunEvent.kind == "handoff.execution_started"))).scalars().all()
    assert len(starts) == 1 and starts[0].actor_id == c.p.id
    assert await records.main_session_id(db, c.parent) == c.original_session.id
    with pytest.raises(HTTPException):
        await service.accept_handoff(db, c.row.id, c.p, action(c.row),
            rights_evaluator=permissions.rights_evaluator, allocator=allocation.allocate_child)


async def test_terminal_child_is_swept_into_original_parent_session_without_duplicate_completion(db):
    c = await graph_case(db)
    binding, child = await started(db, c)
    result = await submit_output(db, child, "submit_definition_of_ready", {
        "type": "task", "summary": "Received approved task", "repository": child.repository})
    assert result["state"] == "recorded"
    await engine.resolve_current_node(db, child, None, actor_id=c.p.id)
    await db.commit()
    assert child.status == "completed" and c.parent.status == "waiting"
    await lifecycle.sweep_handoffs(db)
    assert (c.parent.status, c.parent.outcome) == ("completed", "done")
    assert await records.main_session_id(db, c.parent) == c.original_session.id
    assert await records.main_session_id(db, child) == binding["receiver_session_id"]
    await lifecycle.sweep_handoffs(db)
    terminal = (await db.execute(select(func.count()).select_from(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == c.parent.id, WorkflowRunEvent.kind == "completed"))).scalar_one()
    assert terminal == 1


@pytest.mark.parametrize("drift", ["epoch", "membership", "source", "runtime"])
async def test_stale_receiver_cannot_dispatch_or_record_output(db, drift):
    c = await graph_case(db)
    binding, child = await started(db, c)
    if drift == "epoch":
        await owner_lifecycle.revoke_owner(db, c.row.id, reason="fixture authority revoked")
    elif drift == "membership":
        await db.execute(delete(UserProject).where(UserProject.user_id == c.p.id))
    elif drift == "source":
        c.parent.context = {**c.parent.context, "outputs": {"definition_of_ready": {
            **c.parent.context["outputs"]["definition_of_ready"], "record": {"summary": "unapproved"}}}}
    else:
        child.context = {**child.context, "runtime_target": {"kind": "terminal"}}
    await db.commit()
    before = dict(child.context)
    context = ToolContext(user_id=c.p.id, project_ids=[c.parent.project_id], roles=["viewer"],
        session_id=binding["receiver_session_id"], project_config={}, db=db)
    # Local structured-output tool, not a provider call: the actual registry's FIRST gate must refuse.
    dispatched = await execute_tool("submit_definition_of_ready", {"summary": "unauthorized"}, context)
    expected = {"epoch": "stale_owner", "membership": "not_handoff_recipient",
                "source": "source_changed", "runtime": "stale_owner"}[drift]
    assert dispatched.get("status") == "refused" and dispatched.get("reason") == expected
    with pytest.raises(records.WorkflowRunError):
        await submit_output(db, child, "submit_definition_of_ready", {"type": "task", "repository": child.repository})
    assert child.context == before and "outputs" not in child.context


@pytest.mark.parametrize("detached", [False, True])
async def test_parent_abort_respects_detach_and_prevents_old_receiver_when_not_detached(db, detached):
    c = await graph_case(db, detached=detached)
    binding, child = await started(db, c)
    await lifecycle.abort_children(db, c.parent)
    c.parent.status = "stopped"
    await db.commit()
    if detached:
        assert child.status == "running" and c.row.state == "accepted"
        assert await lifecycle.guard_receiver(db, child) is c.row
    else:
        assert child.status == "stopped" and c.row.state == "stopped"
        with pytest.raises(records.WorkflowRunError):
            await lifecycle.guard_receiver(db, child)


async def test_legacy_list_subworkflow_keeps_same_owner_and_shared_session(db):
    c = await graph_case(db, legacy=True)
    assert c.parent.status != "failed", c.parent.last_error
    assert (await db.execute(select(func.count()).select_from(WorkflowHandoff).where(
        WorkflowHandoff.parent_run_id == c.parent.id))).scalar_one() == 0
    child = (await db.execute(select(WorkflowRun).where(WorkflowRun.parent_run_id == c.parent.id))).scalar_one()
    assert child.requested_by == c.sender.id and child.current_node_id == "read"
    assert await records.main_session_id(db, child) == c.original_session.id
    assert await lifecycle.child_offer(db, child) is None
    assert "definition_of_ready" in child.context["handoff"]


async def test_sweep_persists_membership_owner_loss_before_next_dispatch(db):
    c = await graph_case(db)
    binding, child = await accepted(db, c)  # committed pending-start recovery goes through the real guard
    await db.execute(delete(UserProject).where(UserProject.user_id == c.p.id))
    await db.commit()
    await lifecycle.sweep_handoffs(db)
    await db.refresh(c.row)
    assert c.row.state == "owner_lost" and c.row.owner_epoch > binding["owner_epoch"]
    assert child.current_node_id is None  # sweep did not initialize an unauthorized receiver
    with pytest.raises(records.WorkflowRunError):
        await lifecycle.guard_receiver(db, child)


async def test_nested_handoff_acquires_outer_parent_before_direct_parent(db):
    from sqlalchemy import event
    c = await graph_case(db)
    _, direct_parent = await accepted(db, c)
    # A nested offer descriptor tests lock topology only; no fabricated receiver/evidence execution occurs.
    nested = WorkflowHandoff(parent_run_id=direct_parent.id, parent_node_id="nested", parent_entry=1,
        parent_state_version=direct_parent.state_version, parent_version_id=direct_parent.flow_definition_version_id,
        child_descriptor=c.row.child_descriptor, workspace_id=c.row.workspace_id, requested_by=c.p.id,
        target_kind="person", target_key=c.q.id, contract=c.row.contract, envelopes=c.row.envelopes,
        acceptance="Nested fixture", detach=False, state="offered", state_version=1, owner_epoch=0, round=1,
        deputy_active=False, payload_hash=c.row.payload_hash, expires_at=c.row.expires_at, owner_history=[])
    db.add(nested)
    await db.commit()
    locked_ids = []
    bind = db.sync_session.get_bind()
    def observe(connection, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        source = getattr(compiled, "statement", None)
        if "workflow_runs" in statement and getattr(source, "_for_update_arg", None) is not None:
            values = list(parameters.values()) if isinstance(parameters, dict) else list(parameters)
            locked_ids.extend(value for value in values if value in {c.parent.id, direct_parent.id})
    event.listen(bind, "before_cursor_execute", observe)
    try:
        await service.lock_handoff(db, nested.id)
    finally:
        event.remove(bind, "before_cursor_execute", observe)
    assert c.parent.id in locked_ids, locked_ids
    assert locked_ids.index(c.parent.id) < locked_ids.index(direct_parent.id), locked_ids


async def test_stale_receiver_cannot_write_a_failed_phase_turn_result(db):
    from app.services.workflow_checks.library import TurnEvidence
    c = await graph_case(db)
    _, child = await started(db, c)
    await owner_lifecycle.revoke_owner(db, c.row.id, reason="revoked before terminal turn recording")
    await db.commit()
    before = dict(child.context)
    with pytest.raises(records.WorkflowRunError):
        await phase_turns.complete_phase_turn(db, child, node_id="read", state="not_verified",
                                         evidence=TurnEvidence(answer="STALE_RESULT_CANARY"))
    assert child.context == before
