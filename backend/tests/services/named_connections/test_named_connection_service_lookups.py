"""Contract: every platform path that talks to a connector
outside a tool call uses the tool router's connection resolution."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, UserLinkedAccount
from app.services.admin.project.named_connection_service import save_named
from app.services.auth import create_access_token
from app.services.named_connections.route_planner import plan_connector, plan_route
from app.services.named_connections.service_config import (
    ConnectionRefusalError,
    service_connection_config,
    usable_connection_ids,
)
from app.services.project.service import get_project_config
from tests.agent_definition_revision_fixtures import make_member, make_user
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.support.named_connection_service_lookups_support import ACCOUNT, OCTRYX, SECOND, _basic, _jira_workspace

pytestmark = pytest.mark.asyncio


OTHER = "557058:00000000-0000-0000-0000-0000000000bb"


class JiraCloud:
    def __init__(self, monkeypatch, accounts: dict[str, str]):
        self.requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            account = accounts.get(f"https://{request.url.host}")
            if request.url.path == "/rest/api/3/user/search":
                return httpx.Response(200, json=[{"accountId": account, "displayName": "Dev Person",
                                                  "emailAddress": "dev@acme.test", "active": True}])
            if request.url.path == "/rest/api/3/user" and request.url.params.get("accountId") == account:
                return httpx.Response(200, json={"accountId": account, "displayName": "Dev Person", "active": True})
            return httpx.Response(404, json={})

        import app.tools.jira_impl._jira_query_search as search

        monkeypatch.setattr(search, "egress_transport", lambda *_a, **_k: httpx.MockTransport(handle))


async def _member(db, workspace_id: str):
    from app.models import Project

    user = await make_user(db, label="dev")
    await make_member(db, user, await db.get(Project, workspace_id), "member")
    await db.commit()
    return user.id, {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def test_linking_by_email_runs_on_the_workspaces_named_jira_connection(client, db, monkeypatch):
    workspace_id = await _jira_workspace(db, ("Jira-Cloud-octryx", OCTRYX, ["BRD"]))
    _user_id, headers = await _member(db, workspace_id)
    jira = JiraCloud(monkeypatch, {OCTRYX: ACCOUNT})

    linked = await client.put("/api/v1/users/me/linked-accounts/atlassian", headers=headers,
                              json={"email": "dev@acme.test", "project_id": workspace_id})

    assert linked.status_code == 200, linked.text
    assert linked.json()["account"]["verification_status"] == "verified"
    row = (await db.execute(select(UserLinkedAccount))).scalars().one()
    assert row.account_id == ACCOUNT
    [request] = jira.requests
    assert f"https://{request.url.host}" == OCTRYX and request.url.path == "/rest/api/3/user/search"
    assert request.headers["Authorization"] == _basic("bot@jira-cloud-octryx.test", "token-jira-cloud-octryx")
    verified = await client.post("/api/v1/users/me/linked-accounts/atlassian/verify", headers=headers,
                                 json={"project_id": workspace_id})
    assert verified.status_code == 200, verified.text
    assert len(jira.requests) == 2 and jira.requests[1].url.path == "/rest/api/3/user"
    assert f"https://{jira.requests[1].url.host}" == OCTRYX


async def test_two_jira_connections_answer_together_and_different_accounts_are_ambiguous(client, db, monkeypatch):
    workspace_id = await _jira_workspace(db, ("Jira-A", OCTRYX, ["BRD"]), ("Jira-B", SECOND, ["OPS"]))
    _user_id, headers = await _member(db, workspace_id)

    jira = JiraCloud(monkeypatch, {OCTRYX: ACCOUNT, SECOND: ACCOUNT})
    same = await client.put("/api/v1/users/me/linked-accounts/atlassian", headers=headers,
                            json={"email": "dev@acme.test", "project_id": workspace_id})
    assert same.status_code == 200, same.text
    assert sorted(request.url.host for request in jira.requests) == ["first-site.atlassian.net", "second.atlassian.net"]

    JiraCloud(monkeypatch, {OCTRYX: ACCOUNT, SECOND: OTHER})
    ambiguous = await client.put("/api/v1/users/me/linked-accounts/atlassian", headers=headers,
                                 json={"email": "dev@acme.test", "project_id": workspace_id})
    assert (ambiguous.status_code, ambiguous.json()["reason"]) == (409, "account_ambiguous")


async def test_an_unscoped_call_runs_on_the_one_usable_connection_and_names_the_candidates_otherwise(db):
    one = await get_project_config(await _jira_workspace(db, ("Jira-A", OCTRYX, ["BRD"])), db)
    plan = plan_route("search_jira_users", {"email": "dev@acme.test"}, one)
    assert [target.name for target in plan.targets] == ["Jira-A"]
    assert usable_connection_ids("jira", one) == [plan.targets[0].id]

    two = await get_project_config(await _jira_workspace(db, ("Jira-A", OCTRYX, ["BRD"]), ("Jira-B", SECOND, ["OPS"])),
                                   db)
    refused = plan_route("search_jira_users", {"email": "dev@acme.test"}, two).refusal
    assert refused["code"] == "connection_ambiguous"
    assert [c["name"] for c in refused["candidates"]] == ["Jira-A", "Jira-B", "default"]
    by_key = plan_route("search_jira_users", {"query": "dev", "project_key": "OPS"}, two)
    assert [target.name for target in by_key.targets] == ["Jira-B"]

    workspace_id = await _jira_workspace(db, ("Jira-A", OCTRYX, ["BRD"]))
    entry = await db.get(BuiltInToolConfig, (await db.execute(
        BuiltInToolConfig.__table__.select().where(BuiltInToolConfig.project_id == workspace_id))).first().id)
    entry.config = {"jira_url": SECOND, "jira_auth_mode": "cloud_api_token", "jira_email": "d@x.test",
                    "jira_token": "t"}
    await db.flush()
    with_default = await get_project_config(workspace_id, db)
    assert plan_route("search_jira_users", {"email": "dev@acme.test"}, with_default).targets == (None,)


async def test_a_single_rule_connector_runs_on_its_only_connection(db):
    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="bitbucket", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="bitbucket", project_id=workspace_id, actor_id=None, payload={
        "name": "Bitbucket-Cloud", "bound_scopes": ["acme/payments"], "bitbucket_deployment": "cloud",
        "bitbucket_url": "https://bitbucket.org", "bitbucket_username": "bot@example.test", "bitbucket_token": "t"})
    config = await get_project_config(workspace_id, db)
    plan = plan_route("search_bitbucket_users", {"account_id": ACCOUNT}, config)
    assert plan.refusal is None and [target.name for target in plan.targets] == ["Bitbucket-Cloud"]


async def test_a_service_resolves_the_connection_of_its_key_with_that_connections_secret(db):
    workspace_id = await _jira_workspace(db, ("Jira-A", OCTRYX, ["BRD"]), ("Jira-B", SECOND, ["OPS"]))
    served = await service_connection_config(db, workspace_id, "jira", keys=("brd",))
    assert (served.name, served.config["jira_url"], served.config["jira_token"]) == ("Jira-A", OCTRYX, "token-jira-a")
    assert served.config["jira_allowed_projects"] == ["BRD"]
    with pytest.raises(ConnectionRefusalError) as unserved:
        await service_connection_config(db, workspace_id, "jira", keys=("RIVER",))
    assert unserved.value.code == "connection_not_configured_for_scope"
    with pytest.raises(ConnectionRefusalError) as mismatch:
        await service_connection_config(db, workspace_id, "jira", keys=("BRD",), explicit_connection="Jira-B")
    assert mismatch.value.code == "connection_scope_mismatch"
    assert plan_connector("jira", await get_project_config(workspace_id, db)).refusal["code"] == "connection_ambiguous"
