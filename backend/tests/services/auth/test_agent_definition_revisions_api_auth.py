"""Authentication and Workspace authorization for the revision API."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentStep
from tests.agent_definition_revision_fixtures import (
    admin_user,
    auth_headers,
    call,
    definition_routes,
    error_body,
    make_definition,
    make_member,
    make_project,
    make_user,
    revision_routes,
)


@pytest.mark.asyncio
async def test_every_route_requires_authentication(client: AsyncClient, db: AsyncSession):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    routes = definition_routes(definition.id) + revision_routes(str(uuid.uuid4()))

    for method, url in routes:
        response = await call(client, method, url)
        assert response.status_code == 401, f"{method} {url} -> {response.status_code}"


@pytest.mark.asyncio
async def test_project_member_can_neither_read_nor_author_revisions(
    client: AsyncClient, db: AsyncSession
):
    admin = await admin_user(db)
    project = await make_project(db)
    member = await make_user(db, label="member")
    author = await make_user(db, label="author")
    await make_member(db, member, project, "member")
    # ``owner`` is the second author role; ``admin`` is exercised below.
    await make_member(db, author, project, "owner")
    definition = await make_definition(db, owner=admin, project_id=project.id, steps=1)
    created = await client.post(
        f"/api/v1/agent-definitions/{definition.id}/revisions",
        headers=auth_headers(author),
    )
    assert created.status_code == 200
    revision_id = created.json()["id"]

    for method, url in definition_routes(definition.id) + revision_routes(revision_id):
        denied = await call(client, method, url, headers=auth_headers(member))
        assert denied.status_code == 403, f"{method} {url} -> {denied.status_code}"


@pytest.mark.asyncio
async def test_project_admin_can_draft_validate_and_publish(
    client: AsyncClient, db: AsyncSession
):
    admin = await admin_user(db)
    project = await make_project(db)
    author = await make_user(db, label="author")
    await make_member(db, author, project, "admin")
    definition = await make_definition(db, owner=admin, project_id=project.id, steps=1)

    created = await client.post(
        f"/api/v1/agent-definitions/{definition.id}/revisions",
        headers=auth_headers(author),
    )
    assert created.status_code == 200
    revision = created.json()
    assert revision["revision_number"] == 1
    assert revision["status"] == "draft"
    # Attribution comes from the token, never from a payload field.
    assert revision["created_by"] == author.id

    validated = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision['id']}/validate",
        headers=auth_headers(author),
    )
    assert validated.status_code == 200
    assert validated.json()["validation"] == {"ok": True, "issues": []}

    published = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision['id']}/publish",
        headers=auth_headers(author),
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_by"] == author.id

    listed = await client.get(
        f"/api/v1/agent-definitions/{definition.id}/revisions",
        headers=auth_headers(author),
    )
    assert listed.status_code == 200
    assert listed.json()["count"] == 1


@pytest.mark.asyncio
async def test_out_of_scope_definition_is_indistinguishable_from_unknown(
    client: AsyncClient, db: AsyncSession
):
    admin = await admin_user(db)
    project = await make_project(db)
    outsider = await make_user(db, label="outsider")
    definition = await make_definition(db, owner=admin, project_id=project.id, steps=1)
    unknown_id = str(uuid.uuid4())

    for method, url in definition_routes(definition.id):
        scoped = await call(client, method, url, headers=auth_headers(outsider))
        unknown = await call(
            client,
            method,
            url.replace(definition.id, unknown_id),
            headers=auth_headers(outsider),
        )
        assert scoped.status_code == unknown.status_code == 404
        assert error_body(scoped) == error_body(unknown)


@pytest.mark.asyncio
async def test_out_of_scope_revision_is_indistinguishable_from_unknown(
    client: AsyncClient, db: AsyncSession
):
    admin = await admin_user(db)
    project = await make_project(db)
    author = await make_user(db, label="author")
    outsider = await make_user(db, label="outsider")
    await make_member(db, author, project, "admin")
    definition = await make_definition(db, owner=admin, project_id=project.id, steps=1)
    created = await client.post(
        f"/api/v1/agent-definitions/{definition.id}/revisions",
        headers=auth_headers(author),
    )
    revision_id = created.json()["id"]
    unknown_id = str(uuid.uuid4())

    for method, url in revision_routes(revision_id):
        scoped = await call(client, method, url, headers=auth_headers(outsider))
        unknown = await call(
            client,
            method,
            url.replace(revision_id, unknown_id),
            headers=auth_headers(outsider),
        )
        assert scoped.status_code == unknown.status_code == 404
        assert error_body(scoped) == error_body(unknown)


@pytest.mark.asyncio
async def test_unassigned_definition_is_private_to_its_owner(
    client: AsyncClient, db: AsyncSession
):
    holder = await make_user(db, label="holder")
    stranger = await make_user(db, label="stranger")
    definition = await make_definition(db, owner=holder, project_id=None, steps=1)

    owned = await client.post(
        f"/api/v1/agent-definitions/{definition.id}/revisions",
        headers=auth_headers(holder),
    )
    assert owned.status_code == 200
    assert owned.json()["created_by"] == holder.id

    for method, url in definition_routes(definition.id):
        denied = await call(client, method, url, headers=auth_headers(stranger))
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_global_admin_reaches_an_unassigned_definition(
    client: AsyncClient, db: AsyncSession
):
    holder = await make_user(db, label="holder")
    admin = await admin_user(db)
    definition = await make_definition(db, owner=holder, project_id=None, steps=1)

    response = await client.get(
        f"/api/v1/agent-definitions/{definition.id}/revisions",
        headers=auth_headers(admin),
    )
    assert response.status_code == 200
    assert response.json() == {
        "definition_id": definition.id,
        "items": [],
        "count": 0,
    }


@pytest.mark.asyncio
async def test_publish_of_an_invalid_revision_returns_422_with_typed_issues(
    client: AsyncClient, db: AsyncSession
):
    admin = await admin_user(db)
    definition = await make_definition(db, owner=admin, steps=1)
    step = (
        await db.execute(select(AgentStep).where(AgentStep.agent_id == definition.id))
    ).scalars().one()
    step.allowed_tools = ["definitely_not_a_tool"]
    await db.flush()

    created = await client.post(
        f"/api/v1/agent-definitions/{definition.id}/revisions",
        headers=auth_headers(admin),
    )
    revision_id = created.json()["id"]

    published = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision_id}/publish",
        headers=auth_headers(admin),
    )
    assert published.status_code == 422
    detail = published.json()["detail"]
    assert detail["ok"] is False
    assert {issue["code"] for issue in detail["issues"]} == {"unknown_tool"}
    assert detail["issues"][0]["subject"] == "definitely_not_a_tool"
