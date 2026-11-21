"""``GET /api/v1/approvals/{id}``: bounded metadata under the central visibility rule.

The scope is ``services/approval/access.approval_visibility_clause``, the same rule as the
list, so every case also checks that the lookup by id agrees with ``GET /api/v1/approvals``:

* the session owner (requester) reads its approval; a stranger gets the same 404 as an
  unknown id;
* anyone who may read the session reads it (a contributor, and an observer too);
* a governance publication approval is read by its requester and a reviewer (a Workspace
  ``admin``/``owner``), not by a plain member.

The response never carries the approval's reason text.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Approval, ModelPolicyRevision, SessionCollaborator
from app.models import Session as ChatSession
from app.services.auth import create_access_token
from app.services.model_policy.governance import KIND_MODEL_POLICY, publish_approval_action
from tests.agent_definition_revision_fixtures import make_member, make_project, make_user
from tests.model_policy_support import publish_model_policy

pytestmark = pytest.mark.asyncio

REASON = "free text the decider wrote"


def _headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _visible(client, user, approval_id: str) -> bool:
    """By id and in the list must agree; returns whether the user sees the approval."""
    by_id = await client.get(f"/api/v1/approvals/{approval_id}", headers=_headers(user))
    listed = await client.get("/api/v1/approvals", params={"status": "pending"}, headers=_headers(user))
    assert by_id.status_code in {200, 404} and listed.status_code == 200
    assert (by_id.status_code == 200) == any(row["id"] == approval_id for row in listed.json())
    return by_id.status_code == 200


async def _session_approval(db):
    project = await make_project(db)
    owner = await make_user(db, label="owner")
    session = ChatSession(id=str(uuid.uuid4()), user_id=owner.id, project_id=project.id, metadata_={})
    db.add(session)
    await db.flush()
    approval = Approval(
        session_id=session.id, requested_by=owner.id, action="tool:get_current_time", status="pending", reason=REASON
    )
    db.add(approval)
    await db.commit()
    return project, owner, session, approval


async def test_the_owner_reads_bounded_metadata_and_a_stranger_gets_404(client, db) -> None:
    _project, owner, session, approval = await _session_approval(db)
    stranger = await make_user(db, label="stranger")
    await db.commit()

    resp = await client.get(f"/api/v1/approvals/{approval.id}", headers=_headers(owner))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {key: body[key] for key in ("id", "kind", "status", "session_id", "requested_by")} == {
        "id": approval.id,
        "kind": "session",
        "status": "pending",
        "session_id": session.id,
        "requested_by": owner.id,
    }
    assert "reason" not in body and REASON not in resp.text
    assert await _visible(client, owner, approval.id)

    refused = await client.get(f"/api/v1/approvals/{approval.id}", headers=_headers(stranger))
    unknown = await client.get(f"/api/v1/approvals/{uuid.uuid4()}", headers=_headers(stranger))
    # Same status and body as an unknown id (the error envelope's request id aside).
    assert refused.status_code == unknown.status_code == 404
    assert {key: value for key, value in refused.json().items() if key != "request_id"} == {
        key: value for key, value in unknown.json().items() if key != "request_id"
    }
    assert not await _visible(client, stranger, approval.id)


async def test_anyone_who_may_read_the_session_reads_its_approval(client, db) -> None:
    _project, _owner, session, approval = await _session_approval(db)
    contributor = await make_user(db, label="contributor")
    observer = await make_user(db, label="observer")
    db.add(
        SessionCollaborator(
            session_id=session.id, user_id=contributor.id, role="contributor", invited_by=session.user_id
        )
    )
    db.add(SessionCollaborator(session_id=session.id, user_id=observer.id, role="observer", invited_by=session.user_id))
    await db.commit()

    assert await _visible(client, contributor, approval.id)
    # Visibility follows session read access; deciding still needs write access.
    assert await _visible(client, observer, approval.id)


async def test_a_governance_approval_is_read_by_its_requester_and_a_reviewer(client, db) -> None:
    project = await make_project(db)
    author = await make_user(db, label="author")
    approver = await make_user(db, label="approver")
    member = await make_user(db, label="member")
    await make_member(db, author, project, "owner")
    await make_member(db, approver, project, "admin")
    await make_member(db, member, project, "member")
    policy = await publish_model_policy(db, project, author, "review-models")
    revision = (
        await db.execute(select(ModelPolicyRevision).where(ModelPolicyRevision.policy_id == policy.id))
    ).scalar_one()
    approval = Approval(
        requested_by=author.id,
        workspace_id=project.id,  # as create_review_approval records it
        action=publish_approval_action(KIND_MODEL_POLICY, revision.id, revision.digest),
        status="pending",
        reason=REASON,
    )
    db.add(approval)
    await db.commit()

    resp = await client.get(f"/api/v1/approvals/{approval.id}", headers=_headers(approver))
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "governance" and REASON not in resp.text
    assert await _visible(client, author, approval.id)
    assert await _visible(client, approver, approval.id)
    # A plain member holds no reviewer role.
    assert not await _visible(client, member, approval.id)
