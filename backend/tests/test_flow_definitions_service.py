"""The flow definition service and API create, validate and publish flows, expose the node registry and require admin auth."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import FlowDefinition, Project, User
from app.services.flow_definitions import create_flow_definition, publish_flow_definition_version
from tests.flow_definitions_support import _flow_payload, _valid_flow_definition, _valid_v2_flow_definition


@pytest.mark.asyncio
async def test_flow_definition_service_create_and_publish(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    created = await create_flow_definition(db, current_user=admin, payload=_flow_payload(project.id))
    await db.commit()
    version = created["versions"][0]
    published = await publish_flow_definition_version(db, version_id=version["id"], current_user=admin)
    await db.commit()
    persisted = await db.get(FlowDefinition, created["id"])

    assert created["status"] == "draft"
    assert version["validation_report"]["valid"] is True
    assert published["status"] == "published"
    assert published["versions"][0]["status"] == "published"
    assert persisted is not None
    assert persisted.current_version_id == version["id"]


@pytest.mark.asyncio
async def test_flow_definition_service_create_and_publish_v2(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    payload = {
        "project_id": project.id,
        "key": "v2-evidence-flow",
        "name": "V2 Evidence Flow",
        "description": "Flow Definition v2 contract smoke.",
        "definition": _valid_v2_flow_definition(),
        "runtime_settings": {"authoring_mode": "visual_builder"},
        "policy_bindings": {"validation_required": True},
    }

    created = await create_flow_definition(db, current_user=admin, payload=payload)
    await db.commit()
    version = created["versions"][0]
    published = await publish_flow_definition_version(db, version_id=version["id"], current_user=admin)

    assert created["status"] == "draft"
    assert version["validation_report"]["valid"] is True
    assert version["validation_report"]["schema_version"] == "2.0"
    assert published["status"] == "published"


@pytest.mark.asyncio
async def test_flow_definition_service_rejects_duplicate_project_keys(db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    await create_flow_definition(db, current_user=admin, payload=_flow_payload(project.id))
    with pytest.raises(HTTPException) as exc_info:
        await create_flow_definition(db, current_user=admin, payload=_flow_payload(project.id))

    assert getattr(exc_info.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_flow_definition_api_create_list_get_validate_and_publish(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    create_response = await client.post(
        "/api/v1/flows",
        headers=auth_headers,
        json=_flow_payload(project.id),
    )

    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    version_id = created["versions"][0]["id"]

    validate_response = await client.post(
        "/api/v1/flows/validate",
        headers=auth_headers,
        json={"definition": _valid_flow_definition()},
    )
    publish_response = await client.post(
        f"/api/v1/flows/versions/{version_id}/publish",
        headers=auth_headers,
    )
    list_response = await client.get(
        f"/api/v1/flows?project_id={project.id}",
        headers=auth_headers,
    )
    detail_response = await client.get(f"/api/v1/flows/{created['id']}", headers=auth_headers)

    assert validate_response.status_code == 200, validate_response.text
    assert publish_response.status_code == 200, publish_response.text
    assert list_response.status_code == 200, list_response.text
    assert detail_response.status_code == 200, detail_response.text
    assert validate_response.json()["valid"] is True
    assert publish_response.json()["status"] == "published"
    assert list_response.json()["items"][0]["id"] == created["id"]
    assert detail_response.json()["versions"][0]["definition"]["nodes"][0]["id"] == "ticket-trigger"


@pytest.mark.asyncio
async def test_flow_definition_api_exposes_node_registry(client, auth_headers):
    response = await client.get("/api/v1/flows/node-registry", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    node_types = {item["type"] for item in data["items"]}
    assert data["schema_version"] == "2.0"
    assert {"trigger", "agent_step", "tool_step", "evaluation", "subflow"} <= node_types
    tool_step = next(item for item in data["items"] if item["type"] == "tool_step")
    assert tool_step["calls_tools"] is True
    assert "project_visibility_implications" in tool_step


@pytest.mark.asyncio
async def test_flow_definition_api_requires_admin_auth(client, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    before_count = len((await db.execute(select(FlowDefinition))).scalars().all())
    response = await client.post("/api/v1/flows", json=_flow_payload(project.id))
    after_count = len((await db.execute(select(FlowDefinition))).scalars().all())

    assert response.status_code == 401
    assert after_count == before_count
