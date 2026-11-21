"""Admins manage the project lifecycle, the system default project is protected, and only admins choose the default workspace and its classification level."""

import pytest
from sqlalchemy import select

from app.models import User
from app.services.auth import create_access_token
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace


async def _set_default(db, level):
    """The default level is published through a governed classification version."""
    from sqlalchemy import select

    from app.models import User
    from app.services.knowledge.projection.workspace_classification_default import set_instance_default

    admin = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    await set_instance_default(db, classification=level, actor_id=admin, apply_to_unclassified=False)
    await db.commit()


@pytest.mark.asyncio
async def test_admin_can_manage_project_lifecycle(client, auth_headers):
    created = await client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "managed-project", "description": "Initial", "config": {"owner": "platform"}},
    )
    assert created.status_code == 200, created.text
    project = created.json()
    assert project["source_type"] == "manual"
    assert project["is_system"] is False

    updated = await client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=auth_headers,
        json={"description": "Updated", "config": {"owner": "admin"}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Updated"
    # config is merged: the provided key changes, the creation defaults stay.
    assert updated.json()["config"]["owner"] == "admin"
    assert "trace_capture" in updated.json()["config"]

    archived = await client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_headers)
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_active"] is False
    assert archived.json()["template_metadata"]["archived"] is True

    restored = await client.post(f"/api/v1/projects/{project['id']}/restore", headers=auth_headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_active"] is True
    assert restored.json()["template_metadata"]["archived"] is False

    deleted = await client.delete(f"/api/v1/projects/{project['id']}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["is_active"] is False
    assert deleted.json()["template_metadata"]["deleted"] is True
    assert deleted.json()["template_metadata"]["delete_mode"] == "soft"


@pytest.mark.asyncio
async def test_system_default_project_is_protected(client, auth_headers):
    projects = await client.get("/api/v1/projects", headers=auth_headers)
    assert projects.status_code == 200, projects.text
    default_project = next(project for project in projects.json() if project["name"] == "default")

    archived = await client.post(f"/api/v1/projects/{default_project['id']}/archive", headers=auth_headers)
    assert archived.status_code == 400

    deleted = await client.delete(f"/api/v1/projects/{default_project['id']}", headers=auth_headers)
    assert deleted.status_code == 400

    deactivated = await client.patch(
        f"/api/v1/projects/{default_project['id']}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 400


@pytest.mark.asyncio
async def test_a_new_workspace_gets_the_instance_default_level_at_creation(client, auth_headers, db):
    """The Instance default is applied at creation; a submitted level wins."""
    await _set_default(db, "confidential")

    created = await client.post("/api/v1/projects", headers=auth_headers, json={"name": "defaulted-level", "config": {}})
    assert created.status_code == 200, created.text
    assert created.json()["config"]["data_policy"]["classification"] == "confidential"
    view = await client.get(f"/api/v1/workspaces/{created.json()['id']}/data-classification", headers=auth_headers)
    assert view.json()["source"] == "instance_default"

    own = await client.post(
        "/api/v1/projects", headers=auth_headers,
        json={"name": "own-level", "config": {"data_policy": {"classification": "public"}}},
    )
    assert own.status_code == 200, own.text
    assert own.json()["config"]["data_policy"]["classification"] == "public"


@pytest.mark.asyncio
async def test_without_an_instance_default_a_new_workspace_stays_unclassified(client, auth_headers, db):
    await _set_default(db, None)
    created = await client.post("/api/v1/projects", headers=auth_headers, json={"name": "no-default", "config": {}})
    assert created.status_code == 200, created.text
    assert "data_policy" not in created.json()["config"]


@pytest.mark.asyncio
async def test_admin_can_make_another_workspace_the_default(client, auth_headers):
    created = await client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Acme Orders-like", "description": None, "config": {}}
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    made = await client.post(f"/api/v1/projects/{project_id}/make-default", headers=auth_headers)
    assert made.status_code == 200, made.text
    assert made.json()["is_default"] is True

    listed = {project["id"]: project for project in (await client.get("/api/v1/projects", headers=auth_headers)).json()}
    assert listed[project_id]["is_default"] is True
    assert [project["name"] for project in listed.values() if project["is_default"]] == ["Acme Orders-like"]

    admin_rows = (await client.get("/admin/chat/api/panel/projects", headers=auth_headers)).json()
    assert [row["id"] for row in admin_rows if row["is_default"]] == [project_id]

    # The default cannot be archived or deleted while it is the default.
    assert (await client.post(f"/api/v1/projects/{project_id}/archive", headers=auth_headers)).status_code == 400
    assert (await client.delete(f"/api/v1/projects/{project_id}", headers=auth_headers)).status_code == 400

    # Handing the default back to the system workspace releases it again.
    system_id = next(project_id for project_id, project in listed.items() if project["name"] == "default")
    assert (await client.post(f"/api/v1/projects/{system_id}/make-default", headers=auth_headers)).status_code == 200
    archived = await client.post(f"/api/v1/projects/{project_id}/archive", headers=auth_headers)
    assert archived.status_code == 200, archived.text

    # An archived workspace cannot become the default.
    refused = await client.post(f"/api/v1/projects/{project_id}/make-default", headers=auth_headers)
    assert refused.status_code == 400


@pytest.mark.asyncio
async def test_only_admins_set_the_default_workspace(client, auth_headers, db):
    workspace_id = await seed_workspace(db)
    await seed_member(db, workspace_id=workspace_id, role="admin", username="ws-owner")
    await db.commit()
    owner = (await db.execute(select(User).where(User.username == "ws-owner"))).scalar_one()
    token = create_access_token(owner.id)
    refused = await client.post(
        f"/api/v1/projects/{workspace_id}/make-default", headers={"Authorization": f"Bearer {token}"}
    )
    assert refused.status_code == 403
