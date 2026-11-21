"""Private workflow metadata is listed only for authorized project members."""
import json
import uuid

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import select

from app.models import Project, User, UserProject
from app.services.flow_definitions import create_flow_definition, publish_flow_definition_version
from app.web.routers import chat_main
from tests.phased_workflow_fixtures import phased_definition, reviewer_user


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["member", "foreign", "missing", "global"])
async def test_chat_catalog_enforces_membership_before_returning_private_definition(db, monkeypatch, scope):
    suffix = uuid.uuid4().hex[:8]
    member = User(username=f"workflow-member-{suffix}", email=f"workflow-{suffix}@example.com",
                  password_hash="unused", is_active=True)
    allowed = Project(name=f"Workflow project {suffix}", is_active=True)
    foreign = Project(name=f"Private workflow project {suffix}", is_active=True)
    db.add_all([member, allowed, foreign])
    await db.flush()
    db.add(UserProject(user_id=member.id, project_id=allowed.id, role="member"))
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    key = f"private-phased-{suffix}"
    for project in (allowed, foreign):
        created = await create_flow_definition(db, current_user=admin, payload={
            "key": key, "name": "Private run", "definition": phased_definition(), "project_id": project.id,
        })
        await publish_flow_definition_version(
            db, version_id=created["versions"][0]["id"], current_user=await reviewer_user(db))

    async def principal(*args):
        return member

    monkeypatch.setattr(chat_main, "_require_api_user", principal)
    project_id = {"member": allowed.id, "foreign": foreign.id, "missing": str(uuid.uuid4()), "global": ""}[scope]
    request = Request({"type": "http", "method": "GET", "path": "/chat/api/workflows", "headers": []})
    if scope in {"foreign", "missing"}:
        with pytest.raises(HTTPException) as refused:
            await chat_main.chat_workflows_api(request, project_id=project_id, db=db)
        # A foreign Workspace answers exactly like an ID that names no Workspace: an outsider learns nothing.
        assert refused.value.status_code == 404
        if scope == "missing":
            assert refused.value.detail["code"] == "project_not_found"
    else:
        response = await chat_main.chat_workflows_api(request, project_id=project_id, db=db)
        matches = [row for row in json.loads(response.body)["workflows"] if row["key"] == key]
        assert [row["project_id"] for row in matches] == ([allowed.id] if scope == "member" else [])


@pytest.mark.asyncio
async def test_people_never_see_test_fixtures_or_retired_workflows_and_only_admins_ask_for_them(db, monkeypatch):
    """The composer must not list companion-fixture(-running) or the retired team-delivery.
    The flag is set where the fixture is published, never guessed from its name."""
    from app.services.attention import fixtures

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    await fixtures._ensure_workflow(db, admin)
    await fixtures._ensure_workflow(db, admin, fixtures.RUNNING_KEY, fixtures.RUNNING_DEFINITION)
    suffix = uuid.uuid4().hex[:8]
    person = User(username=f"catalog-person-{suffix}", email=f"catalog-{suffix}@example.com",
                  password_hash="unused", is_active=True)
    db.add(person)
    await db.flush()
    principal = {"user": person}

    async def current(*args):
        return principal["user"]

    monkeypatch.setattr(chat_main, "_require_api_user", current)
    request = Request({"type": "http", "method": "GET", "path": "/chat/api/workflows", "headers": []})
    hidden = {"companion-fixture", "companion-fixture-running"}  # team-delivery ships again (optional)

    listed = await chat_main.chat_workflows_api(request, project_id="", db=db)
    keys = {row["key"] for row in json.loads(listed.body)["workflows"]}
    assert not keys & hidden and {"spec-writing", "epic-delivery"} <= keys

    with pytest.raises(HTTPException) as refused:
        await chat_main.chat_workflows_api(request, project_id="", include_hidden=True, db=db)
    assert refused.value.status_code == 403

    principal["user"] = admin
    everything = await chat_main.chat_workflows_api(request, project_id="", include_hidden=True, db=db)
    assert hidden <= {row["key"] for row in json.loads(everything.body)["workflows"]}
