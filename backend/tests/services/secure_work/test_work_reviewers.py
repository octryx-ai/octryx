"""Contract: repository reviewer suggestions from declared owners first, then Workspace members; a
repository without declared owners reads ``missing_setup: repository_owners``."""

from __future__ import annotations

import uuid

from app.models import (
    Project,
    User,
    UserLinkedAccount,
    UserProject,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
)
from app.services.secure_work.reviewers import recommend_reviewers_for_work_item


async def _user(db, name: str, display: str | None = None) -> User:
    user = User(username=name, email=f"{name}@example.test", password_hash="x", display_name=display or name,
                account_type="human", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def test_declared_reviewers_and_owners_first_then_members(db):
    admin = await _user(db, f"adm-{uuid.uuid4().hex[:6]}")
    project = Project(name=f"rv-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    alice, bob, carol = await _user(db, f"alice-{uuid.uuid4().hex[:4]}"), await _user(db, f"bob-{uuid.uuid4().hex[:4]}"), \
        await _user(db, f"carol-{uuid.uuid4().hex[:4]}")
    db.add(UserLinkedAccount(user_id=bob.id, platform="bitbucket_server", username="bob.scm"))
    for user, role in ((alice, "owner"), (bob, "member"), (carol, "member")):
        db.add(UserProject(user_id=user.id, project_id=project.id, role=role))
    record = WorkRepositoryProfile(id=str(uuid.uuid4()), name="claims-api", project_id=project.id, created_by=admin.id,
                                   default_reviewers_json=["bob.scm"], owners_json=["Claims backend team"])
    item = WorkItem(project_id=project.id, source_type="jira", source_instance="rv", source_key=f"CLM-{uuid.uuid4().hex[:4]}",
                    title="t", sync_state="imported", assignee=carol.username)
    db.add_all([record, item])
    await db.flush()
    db.add(WorkItemChangeUnit(work_item_id=item.id, repository_profile_id=record.id, repository_name="claims-api",
                              branch_name="b", created_by=admin.id))
    await db.commit()
    result = await recommend_reviewers_for_work_item(db, item.id, viewer=alice, workspace_id=project.id)
    order = [entry["display_name"] for entry in result["recommendations"]]
    assert order[0] == bob.username and result["recommendations"][0]["scm_username"] == "bob.scm"
    assert order[1] == "Claims backend team" and result["recommendations"][1]["user_id"] is None
    assert order.index(alice.username) < order.index(carol.username), "the assignee comes last"
    assert result["missing_setup"] == []

    record.default_reviewers_json, record.owners_json = [], []
    await db.commit()
    assert (await recommend_reviewers_for_work_item(db, item.id, viewer=alice, workspace_id=project.id))[
        "missing_setup"] == ["repository_owners"]


async def test_the_engineering_profile_routes_are_gone(client, auth_headers):
    assert (await client.get("/api/v1/secure-work/engineering-profiles", headers=auth_headers)).status_code == 404
