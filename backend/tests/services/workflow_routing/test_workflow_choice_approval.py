"""A phased workflow proposal waits on one governed approval record that one answer decides once; a repeated
answer starts nothing."""

from __future__ import annotations

import pytest

from app.models import Approval
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
from tests.scripted_pool_support import (
    scripted_pool,  # noqa: F401 - fixture
    scripted_turns,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.workflow_proposals, pytest.mark.usefixtures("scripted_pool"), pytest.mark.usefixtures("scripted_turns")]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_the_generic_approval_route_decides_the_same_record(client, db, auth_headers, fakes):  # noqa: F811
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
