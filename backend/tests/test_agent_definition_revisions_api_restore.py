"""Restore over HTTP and the panel Agent CRUD over the revision API.

Covers:
  - a restored revision is visible through the existing panel Agent CRUD
  - panel CRUD is unchanged for definitions that have no revisions
  - a snapshot's ``project_id`` is a restore *target*, never authority: moving a
    definition into another Workspace, and unassigning one, both need authority
    where the move lands
  - panel delete still works for an agent that has revisions

Route-level authentication and Workspace scope live in
``test_agent_definition_revisions_api_auth.py``.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinition
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from tests.agent_definition_revision_fixtures import (
    admin_user,
    auth_headers,
    make_definition,
    make_member,
    make_project,
    make_user,
)
from tests.conftest import ADMIN_PASSWORD

# ---------------------------------------------------------------------------
# Panel CRUD over revisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_is_visible_through_existing_panel_agent_crud(
    client: AsyncClient, db: AsyncSession
):
    login = await client.post(
        "/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 303
    admin = await admin_user(db)

    created_agent = await client.post(
        "/admin/chat/api/panel/agents",
        json={
            "name": "Revision Panel Agent",
            "description": "Managed from panel",
            "goal": "Prove panel compatibility",
            "agent_type": "diagnosis",
            "thinking_level": "light",
            "branch_prefix": "octryx",
            "is_active": True,
        },
    )
    assert created_agent.status_code == 200
    agent_id = created_agent.json()["id"]
    step_created = await client.post(
        f"/admin/chat/api/panel/agents/{agent_id}/steps",
        json={
            "name": "Search docs",
            "step_type": "knowledge",
            "instructions": "Use the knowledge map first",
            "success_criteria": "Relevant documentation found",
            "allowed_tools": ["knowledge_search"],
            "is_enabled": True,
        },
    )
    assert step_created.status_code == 200

    revision = (
        await client.post(
            f"/api/v1/agent-definitions/{agent_id}/revisions",
            headers=auth_headers(admin),
        )
    ).json()
    published = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision['id']}/publish",
        headers=auth_headers(admin),
    )
    assert published.status_code == 200

    # Drift the live aggregate through the panel contract only.
    drifted = await client.put(
        f"/admin/chat/api/panel/agents/{agent_id}",
        json={"name": "Drifted Panel Agent", "goal": "Drifted goal"},
    )
    assert drifted.status_code == 200
    assert drifted.json()["name"] == "Drifted Panel Agent"
    extra_step = await client.post(
        f"/admin/chat/api/panel/agents/{agent_id}/steps",
        json={"name": "Added later", "step_type": "analysis", "is_enabled": True},
    )
    assert extra_step.status_code == 200

    restored = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision['id']}/restore",
        headers=auth_headers(admin),
    )
    assert restored.status_code == 200
    assert restored.json()["restored_from_revision_id"] == revision["id"]

    panel_agents = await client.get("/admin/chat/api/panel/agents")
    assert panel_agents.status_code == 200
    panel_agent = next(
        item for item in panel_agents.json() if item["id"] == agent_id
    )
    assert panel_agent["name"] == "Revision Panel Agent"
    assert panel_agent["goal"] == "Prove panel compatibility"
    assert [step["name"] for step in panel_agent["steps"]] == ["Search docs"]
    assert panel_agent["steps"][0]["allowedTools"] == ["knowledge_search"]


@pytest.mark.asyncio
async def test_panel_agent_crud_now_records_one_governed_draft_revision(
    client: AsyncClient, db: AsyncSession
):
    """Panel payloads are unchanged; the write is now governed.

    Without the boundary a panel create produced no revision at all. It passes the
    governed write boundary, so exactly one ``draft`` revision is recorded and
    attributed to the authenticated administrator — while every panel
    request/response shape stays exactly as it was.
    """
    login = await client.post(
        "/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 303
    admin = await admin_user(db)

    created_agent = await client.post(
        "/admin/chat/api/panel/agents",
        json={
            "name": "No Revision Agent",
            "description": "",
            "goal": "",
            "agent_type": "diagnosis",
            "thinking_level": "light",
            "branch_prefix": "octryx",
            "is_active": True,
        },
    )
    assert created_agent.status_code == 200
    agent_id = created_agent.json()["id"]

    revisions = await client.get(
        f"/api/v1/agent-definitions/{agent_id}/revisions", headers=auth_headers(admin)
    )
    assert revisions.status_code == 200
    body = revisions.json()
    assert body["count"] == 1
    recorded = body["items"][0]
    assert recorded["revision_number"] == 1
    assert recorded["status"] == "draft"
    assert recorded["created_by"] == admin.id
    assert recorded["published_at"] is None

    listed = await client.get("/admin/chat/api/panel/agents")
    assert listed.status_code == 200
    payload = next(item for item in listed.json() if item["id"] == agent_id)
    assert payload["name"] == "No Revision Agent"
    assert payload["steps"] == []


# ---------------------------------------------------------------------------
# Restore target Workspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_cannot_move_a_definition_into_an_unauthorized_workspace(
    client: AsyncClient, db: AsyncSession
):
    """A snapshot's ``project_id`` is a restore target, not authority.

    The revision was taken while the definition belonged to a Workspace the
    caller has no role in. The caller is only authorized on the *current*
    (owner-scope) row, so restoring it back into that Workspace must be refused.
    """
    holder = await make_user(db, label="holder")
    other_workspace = await make_project(db)
    definition = await make_definition(
        db, owner=holder, project_id=other_workspace.id, steps=1
    )

    revision = await create_draft_revision(db, definition=definition, created_by=holder.id)
    await publish_revision(db, revision=revision, published_by=holder.id)
    # The Workspace assignment is later removed from the live row.
    definition.project_id = None
    await db.flush()

    denied = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision.id}/restore",
        headers=auth_headers(holder),
    )
    assert denied.status_code == 403
    assert "target Workspace" in denied.json()["detail"]
    assert definition.project_id is None


@pytest.mark.asyncio
async def test_restore_into_the_same_workspace_stays_allowed(
    client: AsyncClient, db: AsyncSession
):
    admin = await admin_user(db)
    project = await make_project(db)
    author = await make_user(db, label="author")
    await make_member(db, author, project, "admin")
    definition = await make_definition(
        db, owner=admin, project_id=project.id, steps=1
    )

    revision = await create_draft_revision(db, definition=definition, created_by=author.id)
    await publish_revision(db, revision=revision, published_by=author.id)

    restored = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision.id}/restore",
        headers=auth_headers(author),
    )
    assert restored.status_code == 200
    assert definition.project_id == project.id


@pytest.mark.asyncio
async def test_restore_cannot_unassign_a_workspace_without_owner_authority(
    client: AsyncClient, db: AsyncSession
):
    """The other direction of the same rule: leaving a Workspace needs authority.

    The snapshot was taken in owner scope, so restoring it would make the
    definition private to its owner. A project ``admin`` who does not own the
    definition has authority inside the Workspace, not over that move.
    """
    owner = await make_user(db, label="owner")
    workspace = await make_project(db)
    definition = await make_definition(db, owner=owner, project_id=None, steps=1)

    revision = await create_draft_revision(db, definition=definition, created_by=owner.id)
    await publish_revision(db, revision=revision, published_by=owner.id)
    # The definition is assigned to a Workspace after the snapshot was taken.
    definition.project_id = workspace.id
    await db.flush()

    project_admin = await make_user(db, label="workspace-admin")
    await make_member(db, project_admin, workspace, "admin")

    denied = await client.post(
        f"/api/v1/agent-definitions/revisions/{revision.id}/restore",
        headers=auth_headers(project_admin),
    )
    assert denied.status_code == 403
    assert "unassign the Workspace" in denied.json()["detail"]
    assert definition.project_id == workspace.id


@pytest.mark.asyncio
async def test_panel_delete_still_works_for_an_agent_with_revisions(
    client: AsyncClient, db: AsyncSession
):
    login = await client.post(
        "/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert login.status_code == 303
    admin = await admin_user(db)

    created_agent = await client.post(
        "/admin/chat/api/panel/agents",
        json={
            "name": "Deletable Revision Agent",
            "agent_type": "diagnosis",
            "thinking_level": "light",
            "branch_prefix": "octryx",
            "is_active": True,
        },
    )
    assert created_agent.status_code == 200
    agent_id = created_agent.json()["id"]
    revision = await client.post(
        f"/api/v1/agent-definitions/{agent_id}/revisions", headers=auth_headers(admin)
    )
    assert revision.status_code == 200

    deleted = await client.delete(f"/admin/chat/api/panel/agents/{agent_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted"}
    assert (
        await db.execute(
            select(AgentDefinition).where(AgentDefinition.id == agent_id)
        )
    ).scalar_one_or_none() is None
