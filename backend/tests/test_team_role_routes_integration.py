"""S2a actual JWT/HTTP decisions: scoped role offers never transfer requester execution rights.

Only isolated fixture accounts, SQLite rows and the real route/service boundaries are used.
No auth dependency is overridden, provider is called, or shared fixture is changed.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import delete, select

from app.models import AuditLog, Project, WorkflowRunDecision
from app.models.security.user import UserProject
from app.services.auth import create_access_token
from app.services.workflow_runs.records import bind_session, main_session_id, new_chat_session
from tests.knowledge_evidence_seed_support import seed_outsider
from tests.test_team_role_decider_callers import confirmation, ready
from tests.work_role_support import set_seed_role_active

pytestmark = pytest.mark.asyncio
PREFIX = "/api/v1/workflow-runs"


def headers(user_id):
    return {"Authorization": "Bearer " + create_access_token(user_id)}


async def bound_case(db, **kwargs):
    case, role = await ready(db, **kwargs)
    # Isolate the work-role grant from existing team-mode Session visibility.
    project = await db.get(Project, case.project)
    project.access_mode = "user"
    session = await new_chat_session(db, case.requester, case.project)
    session.title = "PRIVATE REQUESTER THREAD"
    await bind_session(db, case.run, session, actor_id=case.requester.id)
    await db.commit()
    return case, role, session


async def role_rows(client, actor_id):
    result = await client.get("/api/v1/inbox", headers=headers(actor_id))
    assert result.status_code == 200, result.text
    return [row for row in result.json()["waiting"] if row["kind"] == "workflow_run_role_decision"]


async def test_role_inbox_and_actual_jwt_card_authorize_exact_decision_without_execution_transfer(client, db):
    case, _role, session = await bound_case(db)
    rows = await role_rows(client, case.pm.id)
    assert len(rows) == 1 and rows[0]["decision_action"] == {"run_id": case.run.id}
    assert "href" not in rows[0]["link"]
    assert session.id not in json.dumps(rows) and session.title not in json.dumps(rows)
    assert not await role_rows(client, case.requester.id)
    shown = await client.get(f"{PREFIX}/{case.run.id}", headers=headers(case.pm.id))
    assert shown.status_code == 200, shown.text
    card = shown.json()["run"]
    assert card["access"] == "read"
    assert {action["key"] for action in card["actions"]} == {"confirm", "change", "stop"}
    assert card["waiting"]["payload_hash"] == confirmation(case)["payload_hash"]
    result = await client.post(f"{PREFIX}/{case.run.id}/actions", headers=headers(case.pm.id),
                               json={"action": "confirm", "payload_hash": card["waiting"]["payload_hash"]})
    assert result.status_code == 200, result.text
    await db.refresh(case.run)
    await db.refresh(session)
    assert case.run.status == "completed"
    assert case.run.requested_by == case.run.context["execution_identity"] == session.user_id == case.requester.id
    assert await main_session_id(db, case.run) == session.id
    decision = (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == case.run.id))).scalar_one()
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow_decider.decision",
        AuditLog.resource_id == case.run.id))).scalar_one()
    assert decision.decided_by == audit.user_id == case.pm.id
    assert decision.payload_hash == card["waiting"]["payload_hash"]
    assert audit.details["execution_user_id"] == case.requester.id


@pytest.mark.parametrize("suffix", ["", "/messages", "/stream-token"])
async def test_role_does_not_grant_requester_session_reads_or_stream_authority(client, db, suffix):
    case, _role, session = await bound_case(db)
    result = await client.get(f"/api/v1/sessions/{session.id}{suffix}", headers=headers(case.pm.id))
    assert result.status_code in (403, 404), f"Unexpected Session status {result.status_code}"
    assert session.title not in result.text
    banner = await client.get(f"{PREFIX}/by-session/{session.id}", headers=headers(case.pm.id))
    assert banner.status_code == 404


@pytest.mark.parametrize("action", ["abort", "change_runtime", "approve_tool", "continue", "follow_up"])
async def test_role_has_no_general_run_execution_or_tool_approval_actions(client, db, action):
    case, _role, session = await bound_case(db)
    result = await client.post(f"{PREFIX}/{case.run.id}/actions", headers=headers(case.pm.id),
        json={"action": action, "reason": "untrusted role attempt", "runtime_target": {"kind": "server"}})
    assert result.status_code == 403, result.text
    rebound = await client.post(f"{PREFIX}/{case.run.id}/sessions", headers=headers(case.pm.id), json={})
    assert rebound.status_code == 403
    await db.refresh(case.run)
    assert case.run.status == "waiting" and case.run.requested_by == case.requester.id
    assert await main_session_id(db, case.run) == session.id
    assert not (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == case.run.id))).scalars().all()


@pytest.mark.parametrize("revoke", ["role", "membership"])
async def test_old_offer_loses_authority_on_role_or_workspace_revocation(client, db, revoke):
    case, role, _session = await bound_case(db)
    offered = await client.get(f"{PREFIX}/{case.run.id}", headers=headers(case.pm.id))
    assert offered.status_code == 200 and offered.json()["run"]["actions"]
    hash_ = offered.json()["run"]["waiting"]["payload_hash"]
    if revoke == "role":
        await set_seed_role_active(db, role, False)
    else:
        await db.execute(delete(UserProject).where(UserProject.user_id == case.pm.id,
                                                  UserProject.project_id == case.project))
    await db.commit()
    result = await client.post(f"{PREFIX}/{case.run.id}/actions", headers=headers(case.pm.id),
                               json={"action": "confirm", "payload_hash": hash_})
    assert result.status_code in (403, 404), result.text
    assert not await role_rows(client, case.pm.id)
    current = await client.get(f"{PREFIX}/{case.run.id}", headers=headers(case.pm.id))
    if revoke == "role":
        assert current.status_code == 200 and current.json()["run"]["actions"] == []
    else:
        assert current.status_code == 404
    await db.refresh(case.run)
    assert case.run.status == "waiting"
    assert not (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == case.run.id))).scalars().all()


async def test_outsider_and_unauthenticated_actor_never_receive_or_decide_role_card(client, db):
    case, _role, _session = await bound_case(db)
    outsider = await seed_outsider(db)
    await db.commit()
    assert not await role_rows(client, outsider)
    hidden = await client.get(f"{PREFIX}/{case.run.id}", headers=headers(outsider))
    assert hidden.status_code == 404
    denied = await client.post(f"{PREFIX}/{case.run.id}/actions", headers=headers(outsider),
        json=confirmation(case))
    assert denied.status_code == 404
    # Naming another actor in the body is no field of an action at all (unknown fields are refused).
    spoofed = await client.post(f"{PREFIX}/{case.run.id}/actions", headers=headers(outsider),
        json={**confirmation(case), "user_id": case.pm.id})
    assert spoofed.status_code == 422
    anonymous = await client.get(f"{PREFIX}/{case.run.id}")
    assert anonymous.status_code == 401


async def test_role_reply_is_bound_to_current_question_and_actual_jwt_actor(client, db):
    case, _role, session = await bound_case(db, kind="user_conversation")
    shown = await client.get(f"{PREFIX}/{case.run.id}", headers=headers(case.pm.id))
    assert shown.status_code == 200, shown.text
    card = shown.json()["run"]
    assert [action["key"] for action in card["actions"]] == ["reply"]
    stale = await client.post(f"{PREFIX}/{case.run.id}/actions", headers=headers(case.pm.id),
        json={"action": "reply", "reply": "billing", "payload_hash": "sha256:old"})
    assert stale.status_code == 409
    result = await client.post(f"{PREFIX}/{case.run.id}/actions", headers=headers(case.pm.id),
        json={"action": "reply", "reply": "billing", "payload_hash": card["waiting"]["payload_hash"]})
    assert result.status_code == 200, result.text
    decision = (await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == case.run.id))).scalar_one()
    assert decision.decided_by == case.pm.id and decision.payload["reply"] == "billing"
    assert session.user_id == case.run.requested_by == case.requester.id
