"""A phased workflow proposal waits on one governed approval record: the held turn's Product Run attempt ends
explicitly, one answer in the chat or on the generic approval route decides it once, and a repeated answer starts
nothing."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Approval, ProductRun, ProductRunAttempt
from app.models import Session as ChatSession
from app.services.workflow_routing.proposal_approval import PROPOSAL_APPROVAL_ACTION_PREFIX
from tests.chat_phased_workflow_start_support import (  # noqa: F401
    _answer,
    _approval,
    _record,
    _send,
    _settle,
    _workspace,
    fakes,
)

pytestmark = pytest.mark.workflow_proposals


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_held_proposal_waits_on_one_approval_record_and_one_answer_decides_it_once(
    client, db, auth_headers, fakes  # noqa: F811
):
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)

    record = await _record(db, session_id)
    assert (record["status"], record["phased"]) == ("needs_confirmation", True)
    assert state["model_calls"] == 0, "a held proposal never reaches the model"
    approval = await _approval(db, session_id)
    assert approval.action == f"{PROPOSAL_APPROVAL_ACTION_PREFIX}{record['proposal_id']}"
    assert approval.status == "pending"
    approval_id = approval.id
    # The held turn's Product Run attempt ends explicitly (no gate_decision_unmapped).
    [attempt] = (
        await db.execute(
            select(ProductRunAttempt).join(ProductRun, ProductRun.id == ProductRunAttempt.run_id)
            .where(ProductRun.session_id == session_id)
        )
    ).scalars().all()
    assert (attempt.state, attempt.end_reason) == ("needs_approval", "awaiting_workflow_confirmation")
    assert (attempt.gate_status, attempt.gate_decision_source) == ("needs_confirmation", "workflow_proposal")

    response = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert response.status_code == 200, response.text

    db.expire_all()
    decided = await db.get(Approval, approval_id)
    assert decided.status == "approved" and decided.approved_by
    session = await db.get(ChatSession, session_id)
    assert session.metadata_["workflow_proposal_decisions"][record["proposal_id"]] == "apply"
    assert len(state["started"]) == 1

    # A repeated answer is already decided and starts nothing.
    again = await _answer(client, auth_headers, session_id, record["proposal_id"], "apply")
    assert again.status_code == 200 and again.json()["workflowProposalDecision"] == "already_decided"
    assert len(state["started"]) == 1 and state["model_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_the_generic_approval_route_decides_the_same_record(client, db, auth_headers, fakes):  # noqa: F811
    """The surface the Claude Code gateway and the admin panel use: one record, same outcome."""
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    session_id = await _send(client, auth_headers, project_id=project_id)
    approval = await _approval(db, session_id)
    approval_id, record_id = approval.id, approval.action[len(PROPOSAL_APPROVAL_ACTION_PREFIX) :]

    response = await client.post(f"/api/v1/approvals/{approval_id}/reject", json={}, headers=auth_headers)
    assert response.status_code == 200, response.text
    await _settle(session_id)

    db.expire_all()
    session = await db.get(ChatSession, session_id)
    assert session.metadata_["workflow_proposal_decisions"][record_id] == "skip"
    assert (await db.get(Approval, approval_id)).status == "rejected"
    # Rejected: nothing starts and the request is not sent again as a chat turn.
    assert state["started"] == [] and state["model_calls"] == 0
