"""Contract: one home for a user's external accounts.

- a user links, verifies and removes only their own accounts; a platform admin those of anyone; every change is
  audited; an Atlassian account is verified through the Workspace's Jira Cloud connection (else Bitbucket Cloud)
  or found by its exact email (the email is not stored);
- the pull request asks the linked account to review; an unresolved requester never blocks it: opened without
  them, mentioned, ``reviewer_skipped: requester_unresolved``, run card and Inbox say "link your account";
- after linking, the retried step makes them the reviewer, or applies the requester-is-author exception.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import AuditLog, UserLinkedAccount
from app.services.auth import create_access_token
from tests.agent_definition_revision_fixtures import make_member, make_project, make_user
from tests.linked_accounts_support import ACCOUNT

pytestmark = pytest.mark.asyncio




def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


class FakeLookups:
    """The governed tool dispatch of a verification, scripted per tool; every call is recorded."""

    def __init__(self, monkeypatch, answers: dict[str, dict]):
        self.calls: list[tuple[str, dict, list[str]]] = []

        async def execute(tool, params, context):
            self.calls.append((tool, dict(params), list(context.project_ids)))
            return answers.get(tool, {"error": "not configured"})

        import app.tools.registry as registry

        monkeypatch.setattr(registry, "execute_tool_with_plugins", execute)


async def _audit(db, action: str) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).where(AuditLog.action == action))).scalars())


async def test_a_user_links_and_verifies_their_atlassian_account(client, db, monkeypatch):
    member, project, other = await make_user(db, label="dev"), await make_project(db), await make_project(db)
    await make_member(db, member, project, "member")
    headers, member_id, project_id, other_id = _headers(member.id), member.id, project.id, other.id
    await db.commit()
    lookups = FakeLookups(monkeypatch, {"search_jira_users": {
        "users": [{"account_id": ACCOUNT, "display_name": "Dev Person"}]}})

    saved = await client.put("/api/v1/users/me/linked-accounts/atlassian", json={"identifier": ACCOUNT},
                             headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["account"]["verification_status"] == "unverified"
    refused = await client.post("/api/v1/users/me/linked-accounts/atlassian/verify", json={"project_id": other_id},
                                headers=headers)
    assert (refused.status_code, refused.json()["reason"]) == (404, "project_not_found")
    verified = await client.post("/api/v1/users/me/linked-accounts/atlassian/verify", json={"project_id": project_id},
                                 headers=headers)
    assert verified.status_code == 200, verified.text
    account = verified.json()["account"]
    assert (account["verification_status"], account["display_name"], account["identifier"]) == (
        "verified", "Dev Person", ACCOUNT)
    assert lookups.calls == [("search_jira_users", {"account_id": ACCOUNT}, [project_id])]

    listed = (await client.get("/api/v1/users/me/linked-accounts", headers=headers)).json()
    assert [item["platform"] for item in listed["accounts"]] == ["atlassian"]
    assert {item["id"] for item in listed["workspaces"]} == {project_id}
    assert "atlassian" in [item["platform"] for item in listed["platforms"]]
    assert [row.details["user_id"] for row in await _audit(db, "linked_account.saved")] == [member_id]
    assert len(await _audit(db, "linked_account.verification_verified")) == 1

    # Without Jira Cloud the Bitbucket Cloud connection checks it; an account it does not know fails.
    FakeLookups(monkeypatch, {"search_bitbucket_users": {"users": []}})
    failed = await client.post("/api/v1/users/me/linked-accounts/atlassian/verify", json={"project_id": project_id},
                               headers=headers)
    assert failed.json()["account"]["verification_status"] == "failed"
    FakeLookups(monkeypatch, {})
    unconfigured = await client.post("/api/v1/users/me/linked-accounts/atlassian/verify",
                                     json={"project_id": project_id}, headers=headers)
    assert (unconfigured.status_code, unconfigured.json()["reason"]) == (409, "needs_configuration")

    removed = await client.delete("/api/v1/users/me/linked-accounts/atlassian", headers=headers)
    assert removed.json() == {"state": "removed"} and len(await _audit(db, "linked_account.removed")) == 1


async def test_an_atlassian_account_is_found_by_its_exact_email_and_the_email_is_not_stored(client, db, monkeypatch,
                                                                                             auth_headers):
    project = await make_project(db)
    await db.commit()
    email = "someone@atlassian.example"
    lookups = FakeLookups(monkeypatch, {"search_jira_users": {
        "users": [{"account_id": ACCOUNT, "display_name": "Admin Person", "email": email}]}})
    saved = await client.put("/api/v1/users/me/linked-accounts/atlassian", headers=auth_headers,
                             json={"email": email, "project_id": project.id})
    assert saved.status_code == 200, saved.text
    assert saved.json()["account"]["verification_status"] == "verified"
    assert lookups.calls == [("search_jira_users", {"email": email}, [project.id])]
    row = (await db.execute(select(UserLinkedAccount))).scalars().one()
    assert row.account_id == ACCOUNT and email not in json.dumps(
        [row.display_name, row.verification_json, *[item.details for item in await _audit(db, "linked_account.saved")]])

    FakeLookups(monkeypatch, {"search_jira_users": {"users": []}})
    missing = await client.put("/api/v1/users/me/linked-accounts/atlassian", headers=auth_headers,
                               json={"email": "nobody@atlassian.example", "project_id": project.id})
    assert (missing.status_code, missing.json()["reason"]) == (404, "account_not_found")


async def test_users_change_only_their_own_accounts_unless_admin(client, db, auth_headers, auth_user):
    member = await make_user(db, label="dev")
    headers, member_id, admin_id = _headers(member.id), member.id, auth_user.id
    await db.commit()
    for method, path in (("get", f"/api/v1/users/{admin_id}/linked-accounts"),
                         ("put", f"/api/v1/users/{admin_id}/linked-accounts/github"),
                         ("delete", f"/api/v1/users/{admin_id}/linked-accounts/github")):
        refused = await client.request(method.upper(), path, headers=headers,
                                       **({"json": {"identifier": "someone"}} if method == "put" else {}))
        assert (refused.status_code, refused.json()["reason"]) == (403, "not_your_account"), path
    by_admin = await client.put(f"/api/v1/users/{member_id}/linked-accounts/github", headers=auth_headers,
                                json={"identifier": "dev-login"})
    assert by_admin.status_code == 200 and by_admin.json()["account"]["source"] == "admin"
    assert (await _audit(db, "linked_account.saved"))[0].details["by_admin"] is True
    invalid = await client.put("/api/v1/users/me/linked-accounts/atlassian", headers=headers,
                               json={"identifier": "not an id"})
    assert (invalid.status_code, invalid.json()["reason"]) == (400, "invalid_account_id")
    unknown = await client.put("/api/v1/users/me/linked-accounts/svn", headers=headers,
                               json={"identifier": "x"})
    assert unknown.status_code == 404
    workspace = await make_project(db)  # an existing Workspace: github is still not verifiable
    github = await client.post(f"/api/v1/users/{member_id}/linked-accounts/github/verify", headers=auth_headers,
                               json={"project_id": workspace.id})
    assert (github.status_code, github.json()["reason"]) == (409, "not_verifiable")


async def test_the_lookup_tools_read_one_atlassian_account_by_its_id(monkeypatch):
    import httpx

    from app.tools.bitbucket_impl import _bitbucket_cloud
    from app.tools.bitbucket_impl._bitbucket_users import SearchBitbucketUsers
    from app.tools.context import ToolContext
    from app.tools.jira_impl._jira_user_email import account_by_id

    def jira(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/user"
        known = request.url.params["accountId"] == ACCOUNT
        return httpx.Response(200 if known else 404, json={"accountId": ACCOUNT, "displayName": "Dev"} if known else {})

    async with httpx.AsyncClient(transport=httpx.MockTransport(jira)) as client:
        assert [user["displayName"] for user in await account_by_id(
            client, "https://acme.atlassian.net", headers={}, account_id=ACCOUNT)] == ["Dev"]
        assert await account_by_id(client, "https://acme.atlassian.net", headers={}, account_id="1:" + "0" * 36) == []

    def bitbucket(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/2.0/users/{ACCOUNT}":
            return httpx.Response(200, json={"account_id": ACCOUNT, "display_name": "Dev", "nickname": "dev"})
        return httpx.Response(404, json={"type": "error", "error": {"message": "Not found"}})

    monkeypatch.setattr(_bitbucket_cloud, "_transport", lambda: httpx.MockTransport(bitbucket))
    context = ToolContext(user_id="u", project_ids=[], roles=[], session_id=None, project_config={
        "bitbucket_deployment": "cloud", "bitbucket_url": "https://bitbucket.org", "bitbucket_username": "bot@x.test",
        "bitbucket_token": "t"})
    found = await SearchBitbucketUsers().execute({"account_id": ACCOUNT}, context)
    assert [(user["account_id"], user["display_name"]) for user in found["users"]] == [(ACCOUNT, "Dev")]
    assert (await SearchBitbucketUsers().execute({"account_id": "1:" + "0" * 36}, context))["users"] == []
    assert "error" in await SearchBitbucketUsers().execute({"query": "dev"}, context)  # Cloud has no user search
