"""Where approvals and clarifications are decided: on their owning screens.

The chat card / approvals API decides a session approval, the publish flow a governance review, the requester a
clarification, and four-eyes holds on every decide path, including the generic approvals API.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Approval, ClarificationQuestion
from app.services.approval.request_service import ensure_approval_request
from app.services.clarification_service import create_clarification_question
from app.services.governance.approval_rule import set_approval_rule
from tests.observability_support import admin_user, call_as, session_for, user_with_role


async def _governance_review(db, requester) -> Approval:
    approval = Approval(requested_by=requester.id, action="policy_set.publish:test", status="pending")
    db.add(approval)
    await db.commit()
    return approval


@pytest.mark.asyncio
async def test_a_session_approval_is_decided_from_the_owning_screen(client, db):
    admin = await admin_user(db)
    session = await session_for(db, admin)
    approval = await ensure_approval_request(db, requested_by=admin.id, action="tool:bash", reason="ls",
                                             session_id=session.id)
    await db.commit()
    response = await call_as(client, "POST", f"/api/v1/approvals/{approval.id}/reject", admin, json={"reason": "no"})
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert response.json()["reason"] == "ls" and response.json()["decision_note"] == "no"


@pytest.mark.asyncio
async def test_four_eyes_holds_on_the_generic_approvals_api(client, db):
    admin = await admin_user(db)
    other_admin = await user_with_role(db, "admin")
    review = await _governance_review(db, admin)

    own = await call_as(client, "POST", f"/api/v1/approvals/{review.id}/approve", admin, json={"reason": "mine"})
    assert own.status_code == 409 and own.json()["detail"]["code"] == "self_approval_not_allowed"
    assert (await db.get(Approval, review.id)).status == "pending"
    second = await call_as(client, "POST", f"/api/v1/approvals/{review.id}/approve", other_admin, json={"reason": "ok"})
    assert second.status_code == 200 and second.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_single_admin_rule_lets_the_requester_approve_and_rejecting_own_is_always_allowed(client, db):
    admin = await admin_user(db)
    rejected = await _governance_review(db, admin)
    response = await call_as(client, "POST", f"/api/v1/approvals/{rejected.id}/reject", admin, json={"reason": "x"})
    assert response.status_code == 200
    await set_approval_rule(db, rule="single_admin", actor_id=admin.id)
    await db.commit()
    review = await _governance_review(db, admin)
    approved = await call_as(client, "POST", f"/api/v1/approvals/{review.id}/approve", admin, json={"reason": "solo"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_the_removed_admin_pages_have_no_decide_routes(client, db):
    admin = await admin_user(db)
    review = await _governance_review(db, admin)
    for method, path in (("GET", "/admin/chat/api/panel/approvals"),
                         ("POST", f"/admin/chat/api/panel/approvals/{review.id}/approve"),
                         ("POST", f"/admin/chat/api/panel/approvals/{review.id}/reject")):
        assert (await call_as(client, method, path, admin)).status_code in {404, 405}


@pytest.mark.asyncio
async def test_a_reply_in_the_thread_answers_the_open_clarification(client, db):
    from app.services.clarification_service import answer_open_clarification_with_reply

    admin = await admin_user(db)
    session = await session_for(db, admin)
    question = await create_clarification_question(
        db, session_id=session.id, project_id=None, run_id=None, question_id="env", question_text="Which environment?",
        context_json={}, requested_by=admin.id, priority="medium")
    await db.commit()

    answered = await answer_open_clarification_with_reply(db, session_id=session.id, answered_by=admin.id,
                                                           reply="staging")
    await db.commit()

    assert answered is not None
    row = (await db.execute(select(ClarificationQuestion).where(ClarificationQuestion.id == question.id))).scalar_one()
    assert (row.status, row.answer_text, row.answered_by) == ("answered", "staging", admin.id)
    assert await answer_open_clarification_with_reply(db, session_id=session.id, answered_by=admin.id, reply="x") is None


@pytest.mark.asyncio
async def test_the_inbox_lists_what_i_can_decide_and_what_waits_on_others(client, db):
    admin = await admin_user(db)
    member = await user_with_role(db, "operator")
    other_admin = await user_with_role(db, "admin")
    member_session = await session_for(db, member)
    tool = await ensure_approval_request(db, requested_by=member.id, action="tool:deploy", reason="deploy",
                                         session_id=member_session.id)
    await create_clarification_question(db, session_id=member_session.id, project_id=None, run_id=None,
                                        question_id="env", question_text="Which environment?", context_json={},
                                        requested_by=member.id)
    mine = await _governance_review(db, admin)
    theirs = await _governance_review(db, other_admin)
    await db.commit()

    member_inbox = (await call_as(client, "GET", "/api/v1/inbox", member)).json()
    assert {item["kind"] for item in member_inbox["waiting"]} == {"tool_approval", "clarification"}
    assert all(item["link"]["href"] == f"/chat?session_id={member_session.id}" for item in member_inbox["waiting"])

    # Another user's tool approval is that user's consent and their chat: not in an admin's Inbox.
    admin_session = await session_for(db, admin)
    own_tool = await ensure_approval_request(db, requested_by=admin.id, action="tool:bash", reason="ls",
                                             session_id=admin_session.id)
    await db.commit()
    admin_inbox = (await call_as(client, "GET", "/api/v1/inbox", admin)).json()
    ids = {item["id"] for item in admin_inbox["waiting"]}
    assert own_tool.id in ids and theirs.id in ids and tool.id not in ids and mine.id not in ids
    assert [item["id"] for item in admin_inbox["requested_by_me"]] == [mine.id]
    review = next(item for item in admin_inbox["waiting"] if item["id"] == theirs.id)
    assert review["link"] == {"tab": "cedarPolicies", "label": "Open Policy set"}


@pytest.mark.asyncio
async def test_a_stale_approval_expires_with_a_decision_record(db):
    """The release line's stale-approval expiry (approval_pending_ttl_hours) lands in the decision timeline too."""
    from datetime import timedelta

    from app.models import PolicyDecisionLog
    from app.services.approval.stale_expiry import expire_stale_approvals
    from app.time_utils import utc_now

    admin = await admin_user(db)
    session = await session_for(db, admin)
    approval = await ensure_approval_request(db, requested_by=admin.id, action="tool:bash", reason="ls",
                                             session_id=session.id)
    approval.created_at = utc_now() - timedelta(days=8)
    session.last_activity_at = utc_now() - timedelta(days=8)
    await db.commit()

    assert await expire_stale_approvals(db, ttl_hours=72) >= 1
    await db.refresh(approval)
    assert (approval.status, approval.approved_by, approval.reason) == ("expired", None, "ls")
    record = (await db.execute(select(PolicyDecisionLog).where(
        PolicyDecisionLog.approval_id == approval.id, PolicyDecisionLog.outcome == "expired"))).scalar_one()
    assert record.rule == "time limit reached"
