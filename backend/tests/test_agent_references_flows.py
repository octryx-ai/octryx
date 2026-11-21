"""Agent "Used by": workflow references, their states, and the panel route contract."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlowDefinition, FlowDefinitionVersion, User
from app.services.agent_references import list_agent_references
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_project, make_user
from tests.conftest import ADMIN_PASSWORD


def _definition(agent_id: str | None, *, node_type: str = "agent_step", prompt: str = "Work") -> dict:
    config = {"prompt": prompt} if agent_id is None else {"agent_definition_id": agent_id}
    return {"nodes": [{"id": "work", "type": node_type, "config": config}], "edges": []}


async def _flow(
    db: AsyncSession,
    owner: User,
    name: str,
    definitions: list[dict],
    *,
    project_id: str | None = None,
    published: int | None = None,
    is_active: bool = True,
) -> FlowDefinition:
    """``definitions`` become versions 1..n; ``published`` is the current published version, else drafts."""
    flow = FlowDefinition(
        id=str(uuid.uuid4()),
        key=f"flow-{uuid.uuid4().hex[:8]}",
        name=name,
        project_id=project_id,
        status="published" if published else "draft",
        is_active=is_active,
        created_by=owner.id,
    )
    db.add(flow)
    await db.flush()
    ids = []
    for number, definition in enumerate(definitions, start=1):
        version = FlowDefinitionVersion(
            id=str(uuid.uuid4()),
            flow_id=flow.id,
            version=number,
            status="published" if number == published else "draft",
            definition_json=definition,
            created_by=owner.id,
        )
        db.add(version)
        ids.append(version.id)
    flow.current_version_id = ids[published - 1] if published else ids[-1]
    await db.flush()
    db.expire(flow, ["versions"])
    return flow


def _states(body: dict) -> dict[str, tuple]:
    return {
        item["name"]: (
            item["reference_state"],
            item["revision"],
            item["latest_revision"],
            item["latest_references_agent"],
            item["workspace_id"],
            item["workspace_name"],
        )
        for item in body["workflows"]
    }


@pytest.mark.asyncio
async def test_workflow_reference_states_for_global_and_workspace_flows(db: AsyncSession) -> None:
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin)
    project = await make_project(db)
    uses, other = _definition(agent.id), _definition(str(uuid.uuid4()))
    await _flow(db, admin, "Draft only", [uses, uses])
    await _flow(db, admin, "Live", [uses, other], project_id=project.id, published=1)
    await _flow(db, admin, "Live and draft", [other, uses], published=1)
    await _flow(db, admin, "Superseded", [uses, other])
    await _flow(db, admin, "Supervised", [_definition(agent.id, node_type="supervisor")])
    await _flow(db, admin, "Prompt mention only", [_definition(None, prompt=f"Ask {agent.id}")])
    await _flow(db, admin, "Archived", [uses], is_active=False)
    await _flow(db, admin, "Unrelated", [other])

    body = await list_agent_references(db, user=admin, agent_id=agent.id)

    assert body["agent_id"] == agent.id and body["truncated"] is False
    assert _states(body) == {
        "Draft only": ("current_draft", 2, 2, True, None, None),
        "Live": ("published", 1, 2, False, project.id, project.name),
        "Live and draft": ("current_draft", 2, 2, True, None, None),
        "Superseded": ("older_revision_only", 1, 2, False, None, None),
        "Supervised": ("current_draft", 1, 1, True, None, None),
    }
    assert all(
        set(item)
        == {
            "kind",
            "id",
            "name",
            "workspace_id",
            "workspace_name",
            "reference_state",
            "revision",
            "latest_revision",
            "latest_references_agent",
        }
        for item in body["workflows"]
    )
    assert {item["kind"] for item in body["workflows"]} == {"workflow"}


@pytest.mark.asyncio
async def test_a_published_reference_outranks_a_newer_draft_reference(db: AsyncSession) -> None:
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin)
    await _flow(db, admin, "Both", [_definition(agent.id), _definition(agent.id)], published=1)

    body = await list_agent_references(db, user=admin, agent_id=agent.id)

    assert _states(body) == {"Both": ("published", 1, 2, True, None, None)}


@pytest.mark.asyncio
async def test_a_published_reference_dropped_by_a_newer_draft_says_the_editor_opens_that_draft(
    db: AsyncSession,
) -> None:
    """Regression (link honesty): the editor link opens the latest draft, which no longer uses the agent."""
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin)
    await _flow(db, admin, "Moved on", [_definition(agent.id), _definition(None), _definition(None)], published=1)

    body = await list_agent_references(db, user=admin, agent_id=agent.id)

    assert _states(body) == {"Moved on": ("published", 1, 3, False, None, None)}


@pytest.mark.asyncio
async def test_the_bounded_scan_reports_truncation(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.agent_references.service.MAX_ITEMS_PER_KIND", 1)
    admin = await admin_user(db)
    agent = await make_definition(db, owner=admin)
    await _flow(db, admin, "First", [_definition(agent.id)])
    await _flow(db, admin, "Second", [_definition(agent.id)])

    body = await list_agent_references(db, user=admin, agent_id=agent.id)

    assert len(body["workflows"]) == 1 and body["truncated"] is True


@pytest.mark.asyncio
async def test_workflows_are_not_listed_for_a_caller_outside_the_workflow_api(db: AsyncSession) -> None:
    owner = await make_user(db, label="refs-plain")
    agent = await make_definition(db, owner=owner)
    await _flow(db, owner, "Hidden", [_definition(agent.id)])

    body = await list_agent_references(db, user=owner, agent_id=agent.id)

    assert body == {"agent_id": agent.id, "workflows": [], "truncated": False}


async def _login(client: AsyncClient) -> None:
    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303


@pytest.mark.asyncio
async def test_route_returns_empty_lists_for_an_unused_agent(client: AsyncClient, db: AsyncSession) -> None:
    await _login(client)
    agent = await make_definition(db, owner=await admin_user(db))
    await db.commit()

    response = await client.get(f"/admin/chat/api/panel/agents/{agent.id}/references")

    assert response.status_code == 200, response.text
    assert response.json() == {"agent_id": agent.id, "workflows": [], "truncated": False}


@pytest.mark.asyncio
async def test_route_answers_another_owners_agent_for_a_global_admin(client: AsyncClient, db: AsyncSession) -> None:
    """Agents are shared, not per owner; a global admin governs every agent. Unknown ids stay 404."""
    await _login(client)
    other = await make_user(db, label="refs-other")
    foreign = await make_definition(db, owner=other)
    await db.commit()

    foreign_response = await client.get(f"/admin/chat/api/panel/agents/{foreign.id}/references")
    unknown_response = await client.get(f"/admin/chat/api/panel/agents/{uuid.uuid4()}/references")

    assert foreign_response.status_code == 200, foreign_response.text
    assert foreign_response.json()["agent_id"] == foreign.id
    assert unknown_response.status_code == 404
