"""Bitbucket Data Center repositories as Knowledge sources through a named connection: listing, host checks,
and clones whose credential stays in Git's environment, never in argv or the URL."""

# ruff: noqa: F811  (the shared ``world`` fixture is imported, then requested by name)
from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select

from app.models import AuditLog, ConnectorNamedConnection
from app.services.named_connections.contract import named_secret_field
from app.services.secret import set_secret_value
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.policy_engine_support import bearer
from tests.services.knowledge.sources.knowledge_bitbucket_dc_repositories_support import (
    BASE,
    REPO_URL,
    _author,
    _connection,
    _save_body,
)
from tests.services.knowledge.sources.knowledge_bitbucket_dc_support import SECRET, world  # noqa: F401 - fixture


def _repos(workspace_id: str, connection_id: str) -> str:
    return f"/api/v1/workspaces/{workspace_id}/knowledge/connections/{connection_id}/repositories"


async def test_the_listing_pages_and_searches_with_the_connections_oidc_bearer(client, db, world) -> None:
    workspace_id, user_id = await _author(db)
    connection_id = await _connection(db, [workspace_id])

    connections = await client.get(f"/api/v1/workspaces/{workspace_id}/knowledge/connections", headers=bearer(user_id))
    assert connections.json()["connections"] == [{"id": connection_id, "name": "Bitbucket", "type": "bitbucket",
                                                   "deployment": "datacenter", "host": "bitbucket.example.test"}]
    first = await client.get(_repos(workspace_id, connection_id), headers=bearer(user_id))
    assert first.status_code == 200, first.text
    page = first.json()
    assert (len(page["repositories"]), page["next_start"], page["is_last_page"]) == (25, 25, False)
    assert page["repositories"][0] == {
        "project_key": "SHOP", "slug": "svc-00", "name": "Service 00",
        "repository_url": f"{BASE}/projects/SHOP/repos/svc-00",
        "web_url": f"{BASE}/projects/SHOP/repos/svc-00/browse", "registered": None}
    second = (await client.get(_repos(workspace_id, connection_id), params={"start": 25},
                               headers=bearer(user_id))).json()
    assert (len(second["repositories"]), second["next_start"], second["is_last_page"]) == (5, None, True)

    searched = (await client.get(_repos(workspace_id, connection_id), params={"q": "aws-shop"},
                                 headers=bearer(user_id))).json()
    assert [repo["repository_url"] for repo in searched["repositories"]] == [REPO_URL]
    assert world.requests[-1].url.params["name"] == "aws-shop"
    project = (await client.get(_repos(workspace_id, connection_id), params={"q": "shop/svc-0"},
                                headers=bearer(user_id))).json()
    assert [repo["slug"] for repo in project["repositories"]] == [f"svc-0{index}" for index in range(10)]
    assert project["next_start"] == 25, "a project's listing pages like any other; the name narrows each page"
    assert world.requests[-1].url.path == "/bitbucket/rest/api/1.0/projects/SHOP/repos"

    branch = await client.get(f"{_repos(workspace_id, connection_id)}/SHOP/aws-shop-deployment/"
                              "default-branch", headers=bearer(user_id))
    assert branch.json() == {"default_branch": "main"}
    assert world.idp.issued == 1, "one client credentials grant, cached across the requests"
    assert all(request.headers["Authorization"] == "Bearer tok-1" for request in world.requests)
    assert SECRET not in first.text + branch.text and "tok-" not in first.text + connections.text


async def test_only_authors_of_a_workspace_where_the_connection_is_usable_may_list(client, db, world) -> None:
    workspace_id, user_id = await _author(db)
    _, member_id = await _author(db)
    other_id, other_user = await _author(db)
    connection_id = await _connection(db, [workspace_id])
    reader = await seed_member(db, workspace_id=workspace_id, role="member")

    forbidden = await client.get(_repos(workspace_id, connection_id), headers=bearer(reader))
    assert forbidden.status_code == 403
    assert (await client.get(_repos(workspace_id, connection_id), headers=bearer(member_id))).status_code == 404
    elsewhere = await client.get(_repos(other_id, connection_id), headers=bearer(other_user))
    assert elsewhere.status_code == 409 and elsewhere.json()["detail"]["reason"] == "connection_not_available"
    assert (await client.get(f"/api/v1/workspaces/{other_id}/knowledge/connections",
                             headers=bearer(other_user))).json() == {"connections": []}
    row = await db.get(ConnectorNamedConnection, connection_id)
    row.is_active = False
    await db.commit()
    disabled = await client.get(_repos(workspace_id, connection_id), headers=bearer(user_id))
    assert disabled.json()["detail"]["reason"] == "connection_disabled"
    assert world.requests == [], "nothing is sent for a refused connection"


async def test_a_source_is_saved_on_the_connections_host_with_its_access_mode(client, db, world) -> None:
    workspace_id, user_id = await _author(db)
    other_id = await seed_workspace(db)
    connection_id = await _connection(db, [workspace_id])
    url = f"/api/v1/workspaces/{workspace_id}/knowledge/connectors"

    foreign = await client.put(f"{url}/shop", headers=bearer(user_id), json=_save_body(
        connection_id, repository_url="https://other.example.test/bitbucket/projects/SHOP/repos/x"))
    assert foreign.status_code == 409
    assert foreign.json()["detail"]["reason"] == "repository_not_on_connection_host"
    public = await client.put(f"{url}/shop", headers=bearer(user_id), json=_save_body(
        connection_id, repository_url="https://github.com/octo/repo"))
    assert public.json()["detail"]["reason"] == "repository_not_on_connection_host"
    unlinked = await client.put(f"{url}/shop", headers=bearer(user_id), json=_save_body(None))
    assert unlinked.status_code == 400, "without its connection a Data Center URL is no known host"
    stray_mode = await client.put(f"{url}/shop", headers=bearer(user_id), json={
        **_save_body(None, repository_url="https://github.com/octo/repo"), "access_mode": "read_write"})
    assert stray_mode.status_code == 400

    saved = await client.put(f"{url}/shop", headers=bearer(user_id), json=_save_body(
        connection_id, repository_url=f"{BASE}/scm/shop/aws-shop-deployment.git"))
    assert saved.status_code == 200, saved.text
    described = saved.json()
    assert (described["connection_id"], described["access_mode"]) == (connection_id, "read_only")
    assert described["scope"]["remote"] == REPO_URL and described["scope"]["host_base"] == BASE
    assert described["scope"]["host"] == "bitbucket_datacenter"

    changed = await client.put(f"{url}/shop/access-mode", headers=bearer(user_id), json={"access_mode": "read_write"})
    assert changed.status_code == 200 and changed.json()["access_mode"] == "read_write"
    resaved = await client.put(f"{url}/shop", headers=bearer(user_id), json=_save_body(connection_id, ref="develop"))
    assert resaved.json()["access_mode"] == "read_write", "a re-save without access_mode keeps it"
    listed = (await client.get(_repos(workspace_id, connection_id), params={"q": "aws-shop"},
                               headers=bearer(user_id))).json()
    assert listed["repositories"][0]["registered"] == {"connector_key": "shop", "access_mode": "read_write"}
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "knowledge.connector.access_mode"))).scalars()
    assert [(row.details["before"], row.details["after"]) for row in audit] == [("read_only", "read_write")]

    member = await seed_member(db, workspace_id=other_id, role="admin")
    unavailable = await client.put(f"/api/v1/workspaces/{other_id}/knowledge/connectors/shop", headers=bearer(member),
                                   json=_save_body(connection_id))
    # Not released to that Workspace: the one source rule refuses it before anything is read (``owner_rules``).
    assert unavailable.status_code == 403 and unavailable.json()["detail"]["code"] == "source_connection_not_granted"
    public_source = await client.put(f"{url}/public", headers=bearer(user_id), json={
        "kind": "git_repository", "repository_url": "https://github.com/octo/repo", "ref": "main"})
    no_mode = await client.put(f"{url}/public/access-mode", headers=bearer(user_id), json={"access_mode": "read_write"})
    assert public_source.status_code == 200 and public_source.json()["access_mode"] is None
    assert no_mode.status_code == 409 and no_mode.json()["detail"]["reason"] == "scope_not_allowed"


async def test_make_available_lists_the_authored_workspaces_where_the_connection_is_usable(client, db, world) -> None:
    workspace_id, user_id = await _author(db)
    second, third = await seed_workspace(db, name="b-second"), await seed_workspace(db, name="c-third")
    for project_id, role in ((second, "owner"), (third, "member")):
        await seed_member(db, workspace_id=project_id, role=role, username=f"x{uuid.uuid4().hex[:8]}")
    from app.models.security.user import UserProject

    db.add_all([UserProject(user_id=user_id, project_id=second, role="owner"),
                UserProject(user_id=user_id, project_id=third, role="member")])
    elsewhere = await seed_workspace(db, name="d-unavailable")
    db.add(UserProject(user_id=user_id, project_id=elsewhere, role="admin"))
    await db.commit()
    connection_id = await _connection(db, [workspace_id, second, third])

    answer = await client.get(f"/api/v1/workspaces/{workspace_id}/knowledge/connections/{connection_id}/workspaces",
                              headers=bearer(user_id))
    assert [(item["id"], item["current"]) for item in answer.json()["workspaces"]] == [
        (workspace_id, True), (second, False)]


async def test_a_cloud_connection_lists_its_member_repositories_by_page(db, world) -> None:
    from app.services.knowledge.sources.connection_repositories import list_repositories

    workspace_id, _ = await _author(db)
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="bitbucket", project_id=None, scope_key="global", name="Cloud",
        bound_scopes=[], available_in="all", agent_tools_level="read",
        config={"bitbucket_url": "https://bitbucket.org", "bitbucket_deployment": "cloud",
                "bitbucket_username": "bot@example.test"})
    db.add(row)
    await db.flush()
    stored = await set_secret_value(db, tool_name="bitbucket", project_id=None, value="cloud-api-token",
                                    field_name=named_secret_field("bitbucket_token", row.id))
    row.config = {**row.config, "bitbucket_token_secret_ref": stored.id}
    await db.commit()
    requests: list[httpx.Request] = []

    def cloud(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["page"])
        values = [{"full_name": "acme/payments", "name": "Payments", "mainbranch": {"name": "main"}}] if page == 1 \
            else [{"full_name": "acme/ledger", "name": "Ledger", "mainbranch": {"name": "trunk"}}]
        body = {"values": values, **({"next": "https://api.bitbucket.org/2.0/repositories?page=2"} if page == 1 else {})}
        return httpx.Response(200, json=body)

    first = await list_repositories(db, workspace_id, row.id, q='pay"', transport=httpx.MockTransport(cloud))
    assert first["repositories"] == [{"project_key": "acme", "slug": "payments", "name": "Payments",
                                      "repository_url": "https://bitbucket.org/acme/payments",
                                      "web_url": "https://bitbucket.org/acme/payments", "default_branch": "main",
                                      "registered": None}]
    assert (first["next_start"], requests[0].url.params["q"], requests[0].url.params["role"]) == (
        25, 'name ~ "pay\\""', "member")
    assert requests[0].headers["Authorization"].startswith("Basic ")
    second = await list_repositories(db, workspace_id, row.id, start=25, transport=httpx.MockTransport(cloud))
    assert (second["repositories"][0]["slug"], second["is_last_page"], requests[1].url.params["page"]) == (
        "ledger", True, "2")
