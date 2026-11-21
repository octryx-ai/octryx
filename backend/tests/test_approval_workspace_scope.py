"""Contract: a governance review approval belongs to its Workspace.

- a review records the Workspace of its publication; it is listed and decided by its requester,
  an ``admin``/``owner`` of that Workspace and a global admin; a reviewer of another Workspace
  neither lists nor decides it (404, still pending);
- a review without a Workspace (a platform routing policy) is a global
  admin's only, not its requester's and not every reviewer's;
- ``require_approval_visible`` (the single-approval read rule) answers the same way;
- the publish gate refuses a review of another Workspace (``mismatched``).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Approval, Project, User, UserProject
from app.services.approval.access import require_approval_visible
from app.services.auth.tokens import create_access_token, hash_password
from app.services.model_policy.governance import check_publish_approval, create_review_approval

DIGEST = "sha256:" + "b" * 64


async def _user(db, label: str) -> User:
    user = User(
        id=str(uuid.uuid4()),
        username=f"{label}-{uuid.uuid4().hex[:8]}",
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("scope-Test-Pw-123"),
        display_name=label,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return user


async def _workspace(db, reviewer: User, role: str) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    db.add(UserProject(user_id=reviewer.id, project_id=project.id, role=role))
    await db.commit()
    return project


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _listed(client, user_headers) -> set[str]:
    response = await client.get("/api/v1/approvals", headers=user_headers)
    assert response.status_code == 200
    return {item["id"] for item in response.json()}


@pytest.mark.asyncio
async def test_a_governance_review_is_seen_and_decided_only_inside_its_workspace(client, db, auth_headers):
    requester, owner_a, admin_b = await _user(db, "requester"), await _user(db, "owner-a"), await _user(db, "admin-b")
    workspace_a = await _workspace(db, owner_a, "owner")
    await _workspace(db, admin_b, "admin")
    review = await create_review_approval(
        db,
        kind="model_policy",
        workspace_id=workspace_a.id,
        revision_id=str(uuid.uuid4()),
        digest=DIGEST,
        requested_by=requester.id,
        label="policy@1",
    )
    legacy = Approval(id=str(uuid.uuid4()), requested_by=requester.id, action=f"model_policy.publish:gone:{DIGEST}")
    db.add(legacy)
    await db.commit()
    assert review.workspace_id == workspace_a.id

    # The reviewer of another Workspace: neither listed nor decidable, nor readable.
    assert not {review.id, legacy.id} & await _listed(client, _auth(admin_b))
    for action in ("approve", "reject"):
        refused = await client.post(f"/api/v1/approvals/{review.id}/{action}", json={}, headers=_auth(admin_b))
        assert refused.status_code == 404
    for approval in (review, legacy):
        with pytest.raises(HTTPException) as unseen:
            await require_approval_visible(db, approval=approval, user_id=admin_b.id)
        assert unseen.value.status_code == 404

    # Inside the Workspace: its requester and its owner; the underivable row is admin-only.
    for member in (requester, owner_a):
        listed = await _listed(client, _auth(member))
        assert review.id in listed and legacy.id not in listed
        assert await require_approval_visible(db, approval=review, user_id=member.id) is review
    with pytest.raises(HTTPException):
        await require_approval_visible(db, approval=legacy, user_id=requester.id)
    assert {review.id, legacy.id} <= await _listed(client, auth_headers)

    review_id, owner_headers, owner_id = review.id, _auth(owner_a), owner_a.id
    await db.rollback()
    assert (await db.execute(select(Approval.status).where(Approval.id == review_id))).scalar_one() == "pending"
    decided = await client.post(f"/api/v1/approvals/{review_id}/approve", json={"reason": "ok"}, headers=owner_headers)
    assert decided.status_code == 200 and decided.json()["approved_by"] == owner_id


@pytest.mark.asyncio
async def test_the_publish_gate_refuses_a_review_of_another_workspace(db):
    requester, owner_a = await _user(db, "requester"), await _user(db, "owner-a")
    workspace_a = await _workspace(db, owner_a, "owner")
    workspace_b = await _workspace(db, owner_a, "owner")
    revision_id = str(uuid.uuid4())
    review = await create_review_approval(
        db,
        kind="model_policy",
        workspace_id=workspace_a.id,
        revision_id=revision_id,
        digest=DIGEST,
        requested_by=requester.id,
        label="evaluator@1",
    )
    review.status, review.approved_by = "approved", owner_a.id
    await db.commit()

    def gate(workspace_id: str):
        return check_publish_approval(
            db, kind="model_policy", workspace_id=workspace_id, revision_id=revision_id, digest=DIGEST, approval_id=review.id
        )

    assert (await gate(workspace_b.id)).status == "mismatched"
    assert (await gate(workspace_a.id)).passed
