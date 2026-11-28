"""The flow definition service and API create, validate and publish flows, expose the node registry and require admin auth."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import FlowDefinition, Project
from tests.services.workflow.flow_definitions_support import (
    _flow_payload,
)


@pytest.mark.asyncio
async def test_flow_definition_api_requires_admin_auth(client, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    before_count = len((await db.execute(select(FlowDefinition))).scalars().all())
    response = await client.post("/api/v1/flows", json=_flow_payload(project.id))
    after_count = len((await db.execute(select(FlowDefinition))).scalars().all())

    assert response.status_code == 401
    assert after_count == before_count
