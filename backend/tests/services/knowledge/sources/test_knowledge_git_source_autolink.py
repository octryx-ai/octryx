"""A repository source saved without a connection is linked to the one connection that reads it."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.knowledge.knowledge_source_connectors import router as connectors_router
from app.db import get_db
from app.models import AuditLog, ConnectionDeviation, ConnectorNamedConnection
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.auth import get_current_user
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.git_autolink import AUTO_LINK_AUDIT_ACTION
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_describe import describe_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from app.services.named_connections.contract import named_secret_field
from app.services.secret import set_secret_value
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.services.knowledge.sources.knowledge_github_support import dns  # noqa: F401 - fixture
from tests.services.knowledge.sources.test_knowledge_github_empty_repository import OWNER, REPO, SHA, TOKEN, FakeGitHub

URL = f"https://github.com/{OWNER}/{REPO}"
GIT = {"kind": "git_repository", "repository_url": URL, "ref": "main", "fetch_mode": "remote_git"}


async def _world(db):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    return authorized, user_id


async def _connection(db, workspace_id: str, *, name: str, tool: str = "github", config: dict | None = None,
                      secret: str | None = "github_token", scope: list[str] | None = None) -> ConnectorNamedConnection:
    row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name=tool, project_id=None, scope_key="global",
                                   name=name, bound_scopes=[OWNER], config=dict(config or {"github_owner": OWNER}),
                                   available_in="selected", owner_kind="workspace", owner_workspace_id=workspace_id)
    db.add(row)
    await db.flush()
    if secret:
        stored = await set_secret_value(db, tool_name=tool, field_name=named_secret_field(secret, row.id),
                                        project_id=None, value=TOKEN)
        row.config = {**row.config, f"{secret}_secret_ref": stored.id}
    if scope is not None:
        db.add(ConnectionDeviation(connection_id=row.id, workspace_id=workspace_id,
                                   fields={"knowledge": {"scope": {"repositories": scope}}}))
    await db.flush()
    return row


async def _save(db, authorized, user_id, key: str = "bench", **extra) -> KnowledgeSourceConnector:
    return await configure_connector(db, authorized=authorized, actor_id=user_id,
                                     config=validate_config(connector_key=key, **GIT, **extra))


async def _audits(db) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog).where(AuditLog.action == AUTO_LINK_AUDIT_ACTION))).scalars())


async def test_one_github_connection_with_a_token_and_the_owner_scope_is_linked_on_save_and_audited(db) -> None:
    authorized, user_id = await _world(db)
    github = await _connection(db, authorized.project_id, name="gh-octryx", scope=[OWNER])

    row = await _save(db, authorized, user_id)

    assert row.connection_id == github.id and row.scope["remote"] == URL
    [audit] = await _audits(db)
    assert audit.user_id == user_id and audit.resource_id == row.id
    assert audit.details == {"workspace_id": authorized.project_id, "connector_key": "bench",
                             "connection_id": github.id, "repository": f"{OWNER}/{REPO}"}
    assert TOKEN not in str(audit.details)


@pytest.mark.parametrize("variant", ["without_token", "scope_excludes_repository", "bitbucket_only"])
async def test_a_connection_that_cannot_read_the_repository_is_never_linked(db, variant) -> None:
    authorized, user_id = await _world(db)
    if variant == "without_token":
        await _connection(db, authorized.project_id, name="gh-public", secret=None)
    elif variant == "scope_excludes_repository":
        await _connection(db, authorized.project_id, name="gh-other", scope=[f"{OWNER}/other", "someone-else"])
    else:
        await _connection(db, authorized.project_id, name="bb-cloud", tool="bitbucket", secret="bitbucket_token",
                          config={"bitbucket_deployment": "cloud", "bitbucket_username": "bot"})

    row = await _save(db, authorized, user_id)

    assert row.connection_id is None and await _audits(db) == []
    assert (await describe_connector(db, row))["connection_candidates"] == []


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


async def test_two_matching_connections_refuse_the_save_with_the_candidates_and_an_explicit_choice_is_kept(
    db, http
) -> None:
    client, state = http
    authorized, user_id = await _world(db)
    first = await _connection(db, authorized.project_id, name="gh-a", scope=[OWNER])
    second = await _connection(db, authorized.project_id, name="gh-b")
    await db.commit()
    state["user"] = await fetch_user(db, user_id)
    base = f"/api/v1/workspaces/{authorized.project_id}/knowledge/connectors"
    body = {key: value for key, value in GIT.items()}
    expected = [{"id": first.id, "name": "gh-a", "type": "github"}, {"id": second.id, "name": "gh-b", "type": "github"}]

    picker = await client.get(f"{base}/_git-connection-candidates", params={"repository_url": URL})
    refused = await client.put(f"{base}/bench", json=body)

    assert picker.status_code == 200 and picker.json() == {"repository_url": URL, "candidates": expected}
    assert refused.status_code == 422
    assert refused.json()["detail"] == {"state": "invalid_request", "reason": "connection_choice_required",
                                        "field": "connection_id", "candidates": expected}
    assert TOKEN not in refused.text

    chosen = await client.put(f"{base}/bench", json={**body, "connection_id": second.id})

    assert chosen.status_code == 200 and chosen.json()["connection_id"] == second.id
    assert "connection_candidates" not in chosen.json() and await _audits(db) == []


async def _unlinked_source(db, authorized, user_id) -> KnowledgeSourceConnector:
    return await _save(db, authorized, user_id)


async def test_an_unlinked_source_is_linked_at_its_next_run_and_reads_the_private_repository_with_the_token(
    db, dns  # noqa: F811
) -> None:
    authorized, user_id = await _world(db)
    row = await _unlinked_source(db, authorized, user_id)
    github = await _connection(db, authorized.project_id, name="gh-octryx", scope=["Octryx-AI"])
    assert (await describe_connector(db, row))["connection_candidates"] == [
        {"id": github.id, "name": "gh-octryx", "type": "github"}]
    runtime, _, evidence_index = build_runtime()
    fake = FakeGitHub(files={"README.md": b"# Bench\n"}, private=True)

    run = await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                              transport=httpx.MockTransport(fake.handler))

    assert (run.state, run.reason) == ("completed", None) and run.report["created"] == 1
    row = await db.get(KnowledgeSourceConnector, row.id)
    assert row.connection_id == github.id and row.scope["head_commit"] == SHA
    assert any(host == "api.github.com" and auth == f"Bearer {TOKEN}" for host, _, auth in fake.requests)
    [audit] = await _audits(db)
    assert audit.details["connection_id"] == github.id and audit.details["repository"] == f"{OWNER}/{REPO}"


async def test_several_matching_connections_at_a_run_refuse_it_as_connection_choice_required(db, dns) -> None:  # noqa: F811
    authorized, user_id = await _world(db)
    row = await _unlinked_source(db, authorized, user_id)
    await _connection(db, authorized.project_id, name="gh-a")
    await _connection(db, authorized.project_id, name="gh-b")
    runtime, _, _ = build_runtime()
    fake = FakeGitHub(files={"README.md": b"# Bench\n"}, private=True)

    run = await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id,
                              transport=httpx.MockTransport(fake.handler))

    assert (run.state, run.reason) == ("needs_configuration", "connection_choice_required")
    assert fake.requests == [] and (await db.get(KnowledgeSourceConnector, row.id)).connection_id is None
