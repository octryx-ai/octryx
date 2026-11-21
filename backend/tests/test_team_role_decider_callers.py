"""Scoped node decisions retain hashes, current authority, governance and requester execution identity."""
import pytest
from sqlalchemy import select

from app.models import Approval, AuditLog, FlowDefinitionVersion, Role, UserRole, WorkflowRunDecision
from app.services.workflow_runs.access import require_run_action, run_access
from app.services.workflow_runs.actions import available_actions, perform_action
from app.services.workflow_runs.graph import PhasedNode
from app.services.workflow_runs.hitl import record_reply
from app.services.workflow_runs.hitl_actions import prepare_decision, reply_payload
from app.services.workflow_runs.hitl_decisions import approval_decided, decide
from app.services.workflow_runs.pause import payload_hash
from app.services.workflow_runs.records import WorkflowRunError
from app.services.workflow_runs.states import (
    WAITING_APPROVAL,
    WAITING_CONFIRMATION,
    WAITING_REPLY,
    WAITING_TOOL_APPROVAL,
)
from tests.knowledge_evidence_seed_support import fetch_user, seed_outsider
from tests.test_team_role_decider_policy import assign_pm, setup_case
from tests.work_role_support import set_seed_role_active

pytestmark = pytest.mark.asyncio


async def ready(db, policy="role:product_manager", kind="user_confirmation", watched=False):
    case = await setup_case(db, policy)
    role = await assign_pm(db, case)
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=case.admin.id, role_id=admin_role.id))
    config = {"subject": "advance", **({"decider": policy} if policy is not None else {})}
    if kind == "user_conversation":
        config["question"] = "Which component changes?"
    version = await db.get(FlowDefinitionVersion, case.run.flow_definition_version_id)
    when = None if kind == "user_conversation" else "approved" if kind == "approval" else "confirmed"
    version.definition_json = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"}, {"id": "confirm", "type": kind, "config": config},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}}], "edges": [
        {"id": "first", "source_node_id": "start", "target_node_id": "confirm"},
        {"id": "final", "source_node_id": "confirm", "target_node_id": "done", **({"when": when} if when else {})}]}
    case.node = PhasedNode("confirm", kind, "Decision", config)
    case.run.waiting_kind = {"user_confirmation": WAITING_CONFIRMATION, "approval": WAITING_APPROVAL,
                             "user_conversation": WAITING_REPLY}[kind]
    case.run.node_state = {"entry": 4, "waiting": {"question": config.get("question", "")}}
    await prepare_decision(db, case.run, case.node, actor_id=case.requester.id)
    if watched:
        state = dict(case.run.node_state)
        state["waiting"] = {**state["waiting"], "watched": "confirmed"}
        case.run.node_state = state
    await db.commit()
    return case, role


def confirmation(case):
    return {"action": "confirm", "payload_hash": case.run.node_state["waiting"]["payload_hash"]}


async def test_role_candidate_confirms_only_offered_decision_and_execution_stays_requester(db):
    case, _ = await ready(db)
    assert await run_access(db, case.run, case.pm) == "read"
    assert {item["key"] for item in await available_actions(db, case.run, access="read", user=case.pm)} == {
        "confirm", "change", "stop"}
    assert not await available_actions(db, case.run, access="read", user=case.requester)
    for action in ("abort", "continue", "change_plan", "change_runtime", "approve_tool", "follow_up"):
        with pytest.raises(WorkflowRunError) as refused:
            await require_run_action(db, case.run.id, case.pm, action)
        assert refused.value.code == "run_read_only"
    await perform_action(db, case.run, user=case.pm, body=confirmation(case))
    assert case.run.status == "completed"
    assert case.run.requested_by == case.run.context["execution_identity"] == case.requester.id
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == case.run.id))).scalar_one()
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow_decider.decision",
                                                   AuditLog.resource_id == case.run.id))).scalar_one()
    assert decision.decided_by == audit.user_id == case.pm.id
    assert audit.details["execution_user_id"] == case.requester.id
    assert audit.details["payload_hash"] == decision.payload_hash


@pytest.mark.parametrize("actor_kind", ["requester", "admin", "stranger"])
async def test_direct_decision_has_no_admin_requester_or_stranger_bypass(db, actor_kind):
    case, _ = await ready(db)
    actor = getattr(case, actor_kind, None) or await fetch_user(db, await seed_outsider(db))
    with pytest.raises(WorkflowRunError) as refused:
        await decide(db, case.run, user=actor, action="confirm", body=confirmation(case))
    assert refused.value.code == "not_decider" and case.run.status == "waiting"
    assert not (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == case.run.id))).scalars().all()


async def test_role_revocation_after_offer_is_rechecked_on_direct_service(db):
    case, role = await ready(db)
    assert await available_actions(db, case.run, access="read", user=case.pm)
    await set_seed_role_active(db, role, False)
    await db.commit()
    with pytest.raises(WorkflowRunError) as refused:
        await decide(db, case.run, user=case.pm, action="confirm", body=confirmation(case))
    assert refused.value.code == "decider_unresolved" and case.run.status == "waiting"


async def test_stale_hash_remains_refused_without_audit(db):
    case, _ = await ready(db)
    with pytest.raises(WorkflowRunError) as refused:
        await perform_action(db, case.run, user=case.pm, body={"action": "confirm", "payload_hash": "old"})
    assert refused.value.code == "payload_changed" and case.run.status == "waiting"
    assert not (await db.execute(select(AuditLog).where(AuditLog.resource_id == case.run.id,
                                                      AuditLog.action == "workflow_decider.decision"))).scalars().all()


async def test_watched_confirmation_checks_current_decider_and_hash(db):
    case, _ = await ready(db, watched=True)
    await perform_action(db, case.run, user=case.pm, body=confirmation(case))
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == case.run.id))).scalar_one()
    assert case.run.status == "completed" and decision.decided_by == case.pm.id


async def test_role_never_grants_tool_approval(db):
    case, _ = await ready(db)
    case.run.waiting_kind = WAITING_TOOL_APPROVAL
    await db.commit()
    assert not await available_actions(db, case.run, access="read", user=case.pm)
    with pytest.raises(WorkflowRunError) as refused:
        await decide(db, case.run, user=case.pm, action="approve_tool", body={})
    assert refused.value.code == "not_requester"


async def test_legacy_approval_preserves_another_admin_four_eyes(db):
    case, _ = await ready(db, policy=None, kind="approval")
    assert "approve" in {item["key"] for item in await available_actions(db, case.run, access="write", user=case.admin)}
    await perform_action(db, case.run, user=case.admin, body={"action": "approve"})
    assert case.run.status == "completed" and case.run.requested_by == case.requester.id


async def test_authored_approval_keeps_governance_and_external_callback_rechecks_policy(db):
    case, _ = await ready(db, kind="approval")
    assert not await available_actions(db, case.run, access="read", user=case.pm)
    with pytest.raises(WorkflowRunError) as refused:
        await decide(db, case.run, user=case.pm, action="approve", body={})
    assert refused.value.code == "four_eyes"
    approval = await db.get(Approval, case.run.node_state["waiting"]["approval_id"])
    approval.status, approval.approved_by = "approved", case.admin.id
    await db.flush()
    with pytest.raises(WorkflowRunError) as refused:
        await approval_decided(db, approval, run=case.run)
    assert refused.value.code == "not_decider" and case.run.status == "waiting"


async def test_authored_reply_is_hash_bound_actual_actor_and_no_execution_transfer(db):
    case, _ = await ready(db, kind="user_conversation")
    offered = await available_actions(db, case.run, access="read", user=case.pm)
    assert [item["key"] for item in offered] == ["reply"]
    question_hash = payload_hash(reply_payload(case.run))
    with pytest.raises(WorkflowRunError) as refused:
        await perform_action(db, case.run, user=case.pm, body={"action": "reply", "reply": "billing", "payload_hash": "old"})
    assert refused.value.code == "payload_changed"
    await perform_action(db, case.run, user=case.pm, body={"action": "reply", "reply": "billing", "payload_hash": question_hash})
    assert case.run.status == "completed" and case.run.requested_by == case.requester.id
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == case.run.id))).scalar_one()
    assert decision.decided_by == case.pm.id and decision.payload["reply"] == "billing"


async def test_authored_reply_never_defaults_to_requester_on_internal_call(db):
    case, _ = await ready(db, kind="user_conversation")
    with pytest.raises(WorkflowRunError) as refused:
        await record_reply(db, case.run, "billing")
    assert refused.value.code == "not_decider"
    with pytest.raises(WorkflowRunError):
        await record_reply(db, case.run, "billing", user=case.requester)
    assert case.run.status == "waiting"


async def test_role_admin_approval_passes_four_eyes_and_audits_actual_actor_once(db):
    case, _ = await ready(db, kind="approval")
    role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=case.pm.id, role_id=role.id))
    await db.commit()
    assert "approve" in {item["key"] for item in await available_actions(db, case.run, access="read", user=case.pm)}
    await perform_action(db, case.run, user=case.pm, body={"action": "approve"})
    assert case.run.status == "completed"
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == case.run.id))).scalar_one()
    audits = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow_decider.decision",
                                                     AuditLog.resource_id == case.run.id))).scalars().all()
    assert decision.decided_by == case.pm.id and len(audits) == 1 and audits[0].user_id == case.pm.id


async def test_direct_reply_attributes_question_to_decider_but_session_remains_requester(db):
    from app.models import ClarificationQuestion
    from app.services.workflow_runs.records import new_chat_session

    case, _ = await ready(db, kind="user_conversation")
    session = await new_chat_session(db, case.requester, case.project)
    question = ClarificationQuestion(session_id=session.id, project_id=case.project,
        question_id="caller-fixture", question_text="Which component changes?", requested_by=case.requester.id,
        status="open")
    db.add(question)
    await db.flush()
    state = dict(case.run.node_state)
    state["waiting"] = {**state["waiting"], "clarification_id": question.id}
    case.run.node_state = state
    await db.commit()
    await record_reply(db, case.run, "billing", user=case.pm)
    assert question.answered_by == case.pm.id and question.status == "answered"
    assert session.user_id == case.run.requested_by == case.requester.id
