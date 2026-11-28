""""You in Jira" for "My work": an explicit, per-person choice of an assignee of the Workspace's Jira items."""

from __future__ import annotations

import pytest

from app.models import Project, User, UserProject
from app.models.runtime.secure_work import WorkItem
from app.services.linked_accounts.resolution import account_identifiers
from tests.policy_engine_support import bearer, make_user

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


@pytest.mark.asyncio
async def test_you_in_jira_is_an_explicit_assignee_choice_for_members(client, db):
    project = Project(name="work-me", description="", is_active=True, config={})
    db.add(project)
    await db.flush()
    member = await db.get(User, await make_user(db, admin=False))
    stranger = await db.get(User, await make_user(db, admin=False))
    db.add(UserProject(user_id=member.id, project_id=project.id, role="member"))
    db.add(WorkItem(source_type="jira", source_instance="your-site.atlassian.net", source_key="BRD-1", title="t",
                    project_id=project.id, assignee=ACCOUNT,
                    source_fields_json={"people": {"assignee": {"display": "Alice"}}}))
    await db.commit()
    path = f"/api/v1/workspaces/{project.id}/work/me"
    member_id, stranger_id = member.id, stranger.id

    assert (await client.get(path, headers=bearer(member_id))).json() == {
        "source_type": "jira", "account_id": None, "display_name": None}
    refused = await client.put(path, json={"source_type": "jira", "account_id": "someone-else"},
                               headers=bearer(member_id))
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "unknown_jira_account"
    chosen = await client.put(path, json={"source_type": "jira", "account_id": ACCOUNT}, headers=bearer(member_id))
    assert chosen.json() == {"source_type": "jira", "account_id": ACCOUNT, "display_name": "Alice"}
    assert ACCOUNT.lower() in {value.lower() for value in await account_identifiers(db, member_id)}
    assert (await client.get(path, headers=bearer(stranger_id))).status_code == 404
    cleared = await client.delete(path, headers=bearer(member_id))
    assert cleared.json()["account_id"] is None
