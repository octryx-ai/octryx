"""Workflow C's shipped seed: it reviews independently, is upgraded unless an admin owns it, and an archived seed stays archived."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import FlowDefinition
from app.models.runtime.flow_definition import FlowDefinitionVersion
from app.services.workflow_runs.seeding import definition_digest, phased_seeds, seed_phased_workflows
from tests.phased_workflow_fixtures import admin_user


@pytest.mark.asyncio
async def test_workflow_c_reviews_independently_and_its_shipped_seed_is_upgraded_unless_an_admin_owns_it(db):
    seed = phased_seeds()[0]
    nodes = {node["id"]: node for node in seed["definition"]["nodes"]}
    assert nodes["independent_review"]["type"] == "review"
    assert nodes["review"]["config"]["checks"][0]["type"] == "review_passed"
    admin = await admin_user(db)
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == seed["key"]))).scalar_one()
    current = await db.get(FlowDefinitionVersion, flow.current_version_id)
    assert definition_digest(current.definition_json) == definition_digest(seed["definition"])

    before = current.version
    earlier = {**seed["definition"], "plan_node": "fix"}  # the seed this installation was seeded with
    current.definition_json = earlier
    current.runtime_settings = {**dict(current.runtime_settings or {}), "seed_digest": definition_digest(earlier)}
    await db.flush()
    assert (await seed_phased_workflows(db, admin_user=admin))["updated"] == 1
    await db.refresh(flow)
    upgraded = await db.get(FlowDefinitionVersion, flow.current_version_id)
    assert upgraded.version == before + 1 and upgraded.status == "published"

    upgraded.definition_json = {**seed["definition"], "budget": {"tool_calls": 50}}  # an admin's own change
    await db.flush()
    assert (await seed_phased_workflows(db, admin_user=admin))["updated"] == 0


@pytest.mark.asyncio
async def test_an_archived_seeded_workflow_stays_archived_and_seeding_goes_on(db):
    from app.services.flow_definitions import archive_flow_definition

    seed = phased_seeds()[0]
    admin = await admin_user(db)
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == seed["key"]))).scalar_one()
    current = await db.get(FlowDefinitionVersion, flow.current_version_id)
    earlier = {**seed["definition"], "plan_node": "fix"}  # a seeded version a changed seed would replace
    current.definition_json = earlier
    current.runtime_settings = {**dict(current.runtime_settings or {}), "seed_digest": definition_digest(earlier)}
    flow_id, version_id = flow.id, current.id
    await archive_flow_definition(db, flow_id=flow_id, current_user=admin)
    await db.flush()
    counts = await seed_phased_workflows(db, admin_user=admin)  # no publish that would refuse with flow_archived
    assert counts["updated"] == 0
    flow = await db.get(FlowDefinition, flow_id)
    await db.refresh(flow)
    assert (flow.status, flow.is_active, flow.current_version_id) == ("archived", False, version_id)
