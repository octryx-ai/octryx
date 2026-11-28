"""A person's private Workspace: exactly one each, only its owner has a role in it, and every other path to it
answers 404 or leaves it out."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, Session, User, UserProject, WorkItem
from app.services.access_control import get_project_role_for_user
from app.services.project.private_workspace import (
    OWNER_ROLE,
    ensure_private_workspace,
    hidden_private_ids,
    owned_private_workspace,
)
from app.services.project.service import get_project_access_details
from app.services.session.resource_access import require_session_resource_access
from tests.devices.device_support import user_named
from tests.policy_engine_support import bearer


async def _owner_and_admin(db) -> tuple[User, User, Project]:
    owner = await user_named(db, f"private-owner-{uuid.uuid4().hex[:6]}")
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    private = await ensure_private_workspace(db, owner)
    await db.commit()
    return owner, admin, private


@pytest.mark.asyncio
async def test_everybody_gets_one_private_workspace_and_only_the_owner_has_a_role(db):
    owner, admin, private = await _owner_and_admin(db)
    assert await ensure_private_workspace(db, owner) is private
    assert private.access_mode == "private" and private.owner_user_id == owner.id
    assert await get_project_role_for_user(db, owner.id, private.id) == OWNER_ROLE
    assert await get_project_role_for_user(db, admin.id, private.id) is None

    db.add(UserProject(user_id=admin.id, project_id=private.id, role="admin"))
    private.config = {"role_access_assignments": [{"role_id": "any", "project_roles": ["admin"]}]}
    await db.commit()
    assert await get_project_role_for_user(db, admin.id, private.id) is None
    assert private.id not in {item["id"] for item in await get_project_access_details(admin.id, db)}
    assert private.id in await hidden_private_ids(db, admin.id)
    mine = {item["id"]: item for item in await get_project_access_details(owner.id, db)}
    assert mine[private.id]["role"] == OWNER_ROLE and mine[private.id]["private"] is True


@pytest.mark.asyncio
async def test_admin_routes_naming_a_private_workspace_answer_404(client, db, auth_headers):
    _owner, _admin, private = await _owner_and_admin(db)
    shared = Project(id=str(uuid.uuid4()), name=f"shared-{uuid.uuid4().hex[:6]}", config={})
    db.add(shared)
    await db.commit()
    for path in (f"/admin/chat/api/panel/projects/{private.id}/config", f"/admin/chat/api/panel/projects/{private.id}/access",
                 f"/admin/chat/api/panel/projects/{private.id}/connectors"):
        refused = await client.get(path, headers=auth_headers)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (404, "project_not_found"), path
    assert (await client.get(f"/admin/chat/api/panel/projects/{shared.id}/config", headers=auth_headers)).status_code == 200
    changed = await client.put(f"/admin/chat/api/panel/projects/{private.id}/access", headers=auth_headers,
                               json={"user_ids": []})
    assert changed.status_code == 404
    listed = await client.get("/admin/chat/api/panel/projects", headers=auth_headers)
    assert listed.status_code == 200 and private.id not in {item["id"] for item in listed.json()}


@pytest.mark.asyncio
async def test_an_admin_cannot_read_a_session_in_a_private_workspace(db):
    owner, admin, private = await _owner_and_admin(db)
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=private.id, origin="chat")
    db.add(session)
    await db.commit()
    with pytest.raises(HTTPException) as refused:
        await require_session_resource_access(db, session_id=session.id, user_id=admin.id)
    assert refused.value.status_code == 404
    assert (await require_session_resource_access(db, session_id=session.id, user_id=owner.id)).id == session.id


@pytest.mark.asyncio
async def test_no_work_can_exist_in_a_private_workspace(db):
    owner, _admin, private = await _owner_and_admin(db)
    owner_id = owner.id
    db.add(WorkItem(project_id=private.id, source_type="platform", source_key=f"P-{uuid.uuid4().hex[:6]}",
                    title="x", issue_type="task"))
    with pytest.raises(HTTPException) as refused:
        await db.flush()
    assert refused.value.status_code == 409
    await db.rollback()
    assert await owned_private_workspace(db, owner_id) is not None


@pytest.mark.asyncio
async def test_the_private_workspace_is_the_default_in_the_chat(client, db):
    owner = await user_named(db, f"fresh-{uuid.uuid4().hex[:6]}")
    await db.commit()
    state = await client.get("/chat/api/bootstrap", headers=bearer(owner.id))
    assert state.status_code == 200, state.text
    projects = state.json()["projects"]
    [own] = [item for item in projects if item.get("private")]
    assert own["name"] == "Private" and own["isDefault"] is True
    again = await client.get("/chat/api/bootstrap", headers=bearer(owner.id))
    assert [item["id"] for item in again.json()["projects"] if item.get("private")] == [own["id"]]


@pytest.mark.asyncio
async def test_the_batch_connector_limits_match_the_per_workspace_route_and_leave_private_ones_out(
        client, db, auth_headers):
    from app.models import BuiltInToolConfig

    _owner, _admin, private = await _owner_and_admin(db)
    shop, ops = (Project(id=str(uuid.uuid4()), name=f"{name}-{uuid.uuid4().hex[:6]}", config={})
                 for name in ("shop", "ops"))
    db.add_all([shop, ops])
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=shop.id, is_active=True,
                             config={"confluence_allowed_spaces": [{"space_key": "Coffe", "enabled": True}]}))
    await db.commit()
    url = "/admin/chat/api/panel/connectors/confluence/workspace-limits"
    answer = await client.get(url, headers=auth_headers, params=[("ids", shop.id), ("ids", ops.id),
                                                                ("ids", private.id), ("ids", "unknown")])
    assert answer.status_code == 200
    body = answer.json()
    assert [row["project_id"] for row in body["workspaces"]] == [shop.id, ops.id]
    single = (await client.get(f"/admin/chat/api/panel/projects/{shop.id}/connectors", headers=auth_headers)).json()
    [row] = [item for item in single["connectors"] if item["connector_name"] == "confluence"]
    assert body["workspaces"][0]["project_limits"] == row["project_limits"]
    assert body["inherited_limits"] == row["inherited_limits"] and body["workspaces"][1]["project_limits"] == {}
    assert (await client.get("/admin/chat/api/panel/connectors/nope/workspace-limits",
                             headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_without_a_default_workspace_a_new_private_workspace_still_grants_the_cleared_models(db):
    from app.services.model_gateway.litellm.policy import model_alias_access_decision
    from app.services.project.default_workspace import default_workspace_id

    assert await default_workspace_id(db) is None
    owner = await user_named(db, f"private-owner-{uuid.uuid4().hex[:6]}")
    private = await ensure_private_workspace(db, owner)
    await db.commit()

    assert model_alias_access_decision("demo-gateway-model", private.config).allowed is True
