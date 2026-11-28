"""A repository for runs through a connection (Work › Repositories): the record a run picks, its rights,
the apps it detects, and when a connection gets the repository bound."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import CodeRepository, ConnectorNamedConnection
from app.services.named_connections.contract import named_secret_field
from app.services.secret import set_secret_value
from app.services.secure_work.repositories import run_repository
from app.services.workflow_routing.phased_start_repository import repository_options
from tests.factories import make_project

BASE = "/api/v1/workspaces/{ws}/repositories"


async def _workspace(db) -> str:
    return (await make_project(db, name=f"Demo Shop {uuid.uuid4().hex[:6]}")).id


async def _github(db, ws: str, *, bound: list[str] | None = None, url: str = "http://127.0.0.1:21944/api/v3") -> str:
    row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="github", project_id=ws, scope_key=ws,
                                   name="GitHub (demo)", bound_scopes=bound or [],
                                   config={"github_url": url, "github_owner": "demo-org", "github_owner_type": "org"})
    db.add(row)
    await db.flush()
    stored = await set_secret_value(db, tool_name="github", field_name=named_secret_field("github_token", row.id),
                                    project_id=ws, value="placeholder-token")
    row.config = {**row.config, "github_token_secret_ref": stored.id}
    await db.commit()
    return row.id


def test_the_clone_url_follows_the_connections_host():
    assert run_repository.clone_url("github", {}, "demo-org/demo-shop") == "https://github.com/demo-org/demo-shop.git"
    assert run_repository.clone_url("github", {"github_url": "http://127.0.0.1:21944/api/v3"}, "octryx/demo-shop") \
        == "http://127.0.0.1:21944/octryx/demo-shop.git"
    assert run_repository.clone_url("gitlab", {"gitlab_url": "https://gitlab.example.test/"}, "team/app") \
        == "https://gitlab.example.test/team/app.git"
    assert run_repository.clone_url("bitbucket", {"bitbucket_deployment": "cloud"}, "team/app") \
        == "https://bitbucket.org/team/app.git"
    assert run_repository.clone_url("bitbucket", {"bitbucket_url": "https://scm.example.test"}, "SHOP/app") \
        == "https://scm.example.test/scm/shop/app.git"


@pytest.mark.asyncio
async def test_a_repository_added_through_a_connection_is_what_a_run_picks(client, db, auth_headers, monkeypatch):
    ws = await _workspace(db)
    connection = await _github(db, ws)
    seen = {}

    async def tree(config, repository, branch):
        seen.update(token=config.get("github_token"), repository=repository, branch=branch)
        return ["README.md", "shop/pricing.py", ".octryx/environment.json", "admin/.octryx/environment.json"]

    monkeypatch.setattr(run_repository, "_github_tree", tree)
    listed = (await client.get(BASE.format(ws=ws) + "/connections", headers=auth_headers)).json()["items"]
    assert [(row["id"], row["connector"]) for row in listed] == [(connection, "github")]

    detected = await client.post(BASE.format(ws=ws) + "/detect", headers=auth_headers,
                                 json={"connection_id": connection, "repository": "octryx/demo-shop"})
    assert detected.status_code == 200, detected.text
    body = detected.json()
    assert body["exists"] is True and body["base_branch"] == "main"
    assert body["apps"] == [{"path": ".", "environment_file": ".octryx/environment.json"},
                            {"path": "admin", "environment_file": "admin/.octryx/environment.json"}]
    assert seen == {"token": "placeholder-token", "repository": "octryx/demo-shop", "branch": "main"}

    added = await client.post(BASE.format(ws=ws), headers=auth_headers, json={
        "connection_id": connection, "repository": "octryx/demo-shop", "base_branch": "main",
        "test_command": "python3 -m unittest discover -s tests", "apps": body["apps"],
        "rights": {"pr": False}})
    assert added.status_code == 201, added.text
    repo = (await db.execute(select(CodeRepository).where(CodeRepository.project_id == ws))).scalar_one()
    await db.refresh(repo)
    assert (repo.provider, repo.remote_url, repo.default_branch) == (
        "github", "http://127.0.0.1:21944/octryx/demo-shop.git", "main")
    policy = repo.config_json["operation_policy"]
    assert {key: policy[key] for key in ("read", "branch", "write", "pr", "index")} == {
        "read": True, "branch": True, "write": True, "pr": False, "index": False}, "on by default, pr switched off"
    assert repo.config_json["apps"] == body["apps"]
    assert repo.config_json["coding_setup"]["test_commands"] == ["python3 -m unittest discover -s tests"]
    # The run card's choice: the Workspace's only coding repository, as github:<owner>/<repo>.
    assert [(option["ref"], option["coding"]) for option in await repository_options(db, ws)] == [
        ("github:octryx/demo-shop", True)]
    # An unbound connection serves the Workspace already: it is not narrowed to this repository.
    row = await db.get(ConnectorNamedConnection, connection)
    await db.refresh(row)
    assert row.bound_scopes == []

    again = await client.post(BASE.format(ws=ws), headers=auth_headers,
                              json={"connection_id": connection, "repository": "octryx/demo-shop"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "repository_exists"


@pytest.mark.asyncio
async def test_a_bound_connection_gets_the_new_repository_bound_too(client, db, auth_headers):
    ws = await _workspace(db)
    connection = await _github(db, ws, bound=["octryx/other-app"])
    added = await client.post(BASE.format(ws=ws), headers=auth_headers,
                              json={"connection_id": connection, "repository": "Octryx/Demo-Shop"})
    assert added.status_code == 201, added.text
    row = await db.get(ConnectorNamedConnection, connection)
    await db.refresh(row)
    assert row.bound_scopes == ["octryx/demo-shop", "octryx/other-app"]


@pytest.mark.asyncio
async def test_a_repository_needs_one_of_the_workspaces_connections_and_a_valid_name(client, db, auth_headers):
    ws = await _workspace(db)
    other = await _github(db, await _workspace(db))
    foreign = await client.post(BASE.format(ws=ws), headers=auth_headers,
                                json={"connection_id": other, "repository": "octryx/demo-shop"})
    assert foreign.status_code == 422 and foreign.json()["detail"]["code"] == "connection_not_found"
    connection = await _github(db, ws)
    for name in ("demo-shop", "octryx/../etc", "https://x/octryx/demo"):
        bad = await client.post(BASE.format(ws=ws), headers=auth_headers,
                                json={"connection_id": connection, "repository": name})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "repository_invalid", name
