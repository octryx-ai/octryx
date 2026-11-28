"""One rule for every Knowledge source type (``sources/sync/owner_rules.py``): an owner saves only with a
connection released to the Workspace, and only a platform admin may widen visibility to ``workspace``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.knowledge.knowledge_source_connectors import router as connectors_router
from app.db import get_db
from app.models import BuiltInToolConfig, ConnectionWorkspace, ConnectorNamedConnection, User
from app.models.project.knowledge_source_sync import CONNECTOR_KINDS, KnowledgeSourceConnector
from app.services.auth import get_current_user
from app.services.named_connections.contract import named_secret_field
from app.services.rest_connector.connections import create_connection
from app.services.rest_connector.definitions import create_definition, update_operation
from app.services.secret import set_secret_value
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.support.rest_connector_support import API, SECRET

pytestmark = pytest.mark.usefixtures("public_source_dns")

NOT_GRANTED = "source_connection_not_granted"
VISIBILITY_ADMIN_ONLY = "rest_source_visibility_admin_only"
REST_OPERATIONS = [{"op_key": "list_docs", "method": "GET", "path": "/docs"}]
REST_MAPPING = {"id": "id", "title": "title", "updated_at": "updated"}

# Released: shared with the Workspace. Foreign: another Workspace's own. Unreleased: the platform's, shared with no one.
RELEASED, FOREIGN, UNRELEASED = "released", "foreign", "unreleased"


@dataclass(frozen=True)
class Kind:
    tool: str
    config: dict
    secret_field: str | None
    bound: list[str]
    body: dict


NAMED_KINDS = {
    "jira": Kind("jira", {"jira_url": "https://jira.example.test", "jira_auth_mode": "bearer_pat"}, "jira_token",
                 ["OPS"], {"project_keys": ["OPS"]}),
    "confluence": Kind("confluence", {"confluence_url": "https://wiki.example.test",
                                      "confluence_auth_mode": "bearer_pat"}, "confluence_token", ["OPS"],
                       {"spaces": ["OPS"]}),
    "servicenow": Kind("servicenow", {"servicenow_url": "https://desk.example.test",
                                      "servicenow_auth_mode": "bearer_token"}, "servicenow_token", ["incident"],
                       {"tables": ["incident"]}),
    "kubernetes": Kind("kubernetes", {"k8s_api_url": "https://k8s.example.test"}, "k8s_token", ["prod"],
                       {"cluster": "prod"}),
    "git_repository": Kind("github", {"github_owner": "octo"}, None, ["octo"],
                           {"fetch_mode": "remote_git", "repository_url": "https://github.com/octo/public-repo",
                            "ref": "main"}),
}
ALL_KINDS = sorted(CONNECTOR_KINDS)


def test_every_registered_source_type_is_covered() -> None:
    assert set(ALL_KINDS) == {*NAMED_KINDS, "custom_rest"}


@pytest.fixture
async def http(db):
    app = FastAPI()
    app.include_router(connectors_router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://knowledge.test") as client:
        yield client, state


@dataclass
class World:
    workspace_id: str
    other_id: str
    owner: User
    admin: User


async def _world(db) -> World:
    workspace_id, other_id = await seed_workspace(db), await seed_workspace(db)
    owner_id = await seed_member(db, workspace_id=workspace_id, role="owner", username=f"own{uuid.uuid4().hex[:6]}")
    await db.commit()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    return World(workspace_id, other_id, await fetch_user(db, owner_id), admin)


async def _named_connection(db, world: World, kind: Kind, release: str) -> str:
    owned_by_other = release == FOREIGN
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name=kind.tool, project_id=None, scope_key="global",
        name=f"{kind.tool}-{uuid.uuid4().hex[:6]}", bound_scopes=kind.bound, config=dict(kind.config),
        available_in="selected", agent_tools_level="read", is_active=True,
        owner_kind="workspace" if owned_by_other else "platform",
        owner_workspace_id=world.other_id if owned_by_other else None,
    )
    db.add(row)
    await db.flush()
    if release == RELEASED:
        db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=world.workspace_id))
    if kind.secret_field:
        stored = await set_secret_value(db, tool_name=kind.tool, field_name=named_secret_field(kind.secret_field,
                                                                                               row.id),
                                        project_id=None, value=f"fake-{kind.tool}")
        row.config = {**row.config, f"{kind.secret_field}_secret_ref": stored.id}
    # The Workspace's tool entry: named connections route only while it is active.
    db.add(BuiltInToolConfig(tool_name=kind.tool, project_id=world.workspace_id, config={}, is_active=True))
    await db.commit()
    return row.id


async def _rest_definition(db, world: World, release: str) -> dict:
    key = f"r{uuid.uuid4().hex[:8]}"
    role = f"reader{key}"
    definition = await create_definition(db, {"key": key, "name": "Desk", "auth": {"scheme": "bearer"},
                                               "operations": REST_OPERATIONS}, actor_user_id=world.admin.id)
    connection = {"base_url": API, "token": SECRET}
    if release == FOREIGN:
        connection["project_id"] = world.other_id
    await create_connection(db, definition["id"], connection)
    grant = {"role": role} if release != UNRELEASED else {"role": role, "workspace_id": world.other_id}
    await update_operation(db, definition["id"], definition["operations"][0]["id"], {
        "enabled": True, "grants": [grant], "records_path": "items"})
    await db.commit()
    return {"kind": "custom_rest", "scope": {"definition": key, "operation": "list_docs", "role": role},
            "mapping": REST_MAPPING}


async def _body(db, world: World, kind: str, release: str) -> dict:
    if kind == "custom_rest":
        return await _rest_definition(db, world, release)
    named = NAMED_KINDS[kind]
    return {"kind": kind, **named.body, "connection_id": await _named_connection(db, world, named, release)}


async def _saved(db, world: World, key: str) -> KnowledgeSourceConnector | None:
    return (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == world.workspace_id,
        KnowledgeSourceConnector.connector_key == key))).scalar_one_or_none()


@pytest.mark.parametrize("kind", ALL_KINDS)
async def test_an_owner_creates_every_source_type_with_a_released_connection_and_restricted_visibility(
        db, http, kind: str) -> None:
    client, state = http
    world = await _world(db)
    state["user"] = world.owner
    body = await _body(db, world, kind, RELEASED)

    answer = await client.put(f"/api/v1/workspaces/{world.workspace_id}/knowledge/connectors/src", json=body)

    assert answer.status_code == 200, answer.json()
    row = await _saved(db, world, "src")
    assert row is not None and row.kind == kind
    if kind == "custom_rest":
        # Omitted visibility is saved as restricted: the grants decide who reads the items.
        assert row.scope["visibility"] == "restricted" and answer.json()["acl"]["visibility"] == "restricted"
    else:
        # No visibility setting at all: the source's own ACL decides (restricted items stay withheld/filtered).
        assert "visibility" not in row.scope


@pytest.mark.parametrize("release", [FOREIGN, UNRELEASED])
@pytest.mark.parametrize("kind", ALL_KINDS)
async def test_a_connection_not_released_to_the_workspace_is_403_for_every_source_type(
        db, http, kind: str, release: str) -> None:
    client, state = http
    world = await _world(db)
    body = await _body(db, world, kind, release)
    base = f"/api/v1/workspaces/{world.workspace_id}/knowledge/connectors"

    for user in (world.owner, world.admin):
        state["user"] = user
        answer = await client.put(f"{base}/src", json=body)
        assert answer.status_code == 403, (user.username, answer.json())
        assert answer.json()["detail"]["code"] == NOT_GRANTED
        assert answer.json()["detail"]["field"].startswith(("connection_id", "scope."))
        # The refusal names the connection for a link to Admin › Connections: the id only
        # for a platform admin, the name for others only for a platform connection, never another Workspace's.
        detail = answer.json()["detail"]
        known = not (kind == "custom_rest" and release == FOREIGN)  # no connection serves this Workspace at all
        if user is world.admin:
            assert ("connection_id" in detail and bool(detail["connection_name"])) is known, detail
        else:
            assert "connection_id" not in detail, detail
            assert ("connection_name" in detail) is (release == UNRELEASED), detail
    assert await _saved(db, world, "src") is None
    if kind == "custom_rest":
        state["user"] = world.owner
        sample = await client.post(f"{base}/src/sample", json=body)
        assert sample.status_code == 403 and sample.json()["detail"]["code"] == NOT_GRANTED


async def test_workspace_visibility_is_for_a_platform_admin_only(db, http) -> None:
    client, state = http
    world = await _world(db)
    body = await _body(db, world, "custom_rest", RELEASED)
    wide = {**body, "scope": {**body["scope"], "visibility": "workspace"}}
    base = f"/api/v1/workspaces/{world.workspace_id}/knowledge/connectors"

    state["user"] = world.owner
    refused = await client.put(f"{base}/src", json=wide)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == VISIBILITY_ADMIN_ONLY
    sampled = await client.post(f"{base}/src/sample", json=wide)
    assert sampled.status_code == 403 and sampled.json()["detail"]["code"] == VISIBILITY_ADMIN_ONLY
    assert await _saved(db, world, "src") is None

    state["user"] = world.admin
    allowed = await client.put(f"{base}/src", json=wide)
    assert allowed.status_code == 200 and allowed.json()["acl"]["visibility"] == "workspace"


@pytest.mark.parametrize("kind", sorted(NAMED_KINDS))
async def test_a_built_in_source_type_cannot_be_widened_to_workspace_visibility(db, http, kind: str) -> None:
    client, state = http
    world = await _world(db)
    body = await _body(db, world, kind, RELEASED)
    for user in (world.owner, world.admin):
        state["user"] = user
        answer = await client.put(f"/api/v1/workspaces/{world.workspace_id}/knowledge/connectors/src",
                                  json={**body, "scope": {"visibility": "workspace"}})
        assert answer.status_code in (400, 422), answer.json()
    assert await _saved(db, world, "src") is None

