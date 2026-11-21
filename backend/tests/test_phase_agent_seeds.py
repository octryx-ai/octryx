"""A–E name their phase agents; an admin's version keeps running and gets a changed seed as a draft."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import FlowDefinition
from app.models.runtime.flow_definition import FlowDefinitionVersion
from app.services.workflow_runs.seeding import definition_digest, seed_phased_workflows
from tests.phased_seed_definitions import seed_definitions
from tests.phased_workflow_fixtures import admin_user

pytestmark = pytest.mark.asyncio

EXPECTED = {
    "jira-intake-triage": {"understand": "assistant"},
    # The documentation phase is split into a draft and a final pass.
    "feature-delivery-tdd": {"clarify": "engineer", "tests_first": "engineer", "implement": "engineer",
                             "doc_draft": "engineer", "doc_final": "engineer"},
    "bug-fix-reproduction": {"intake": "engineer", "reproduce": "engineer", "fix": "engineer"},
    "incident-analysis": {"evidence": "assistant", "hypothesis": "assistant"},
}


async def _current(db, key: str) -> tuple[FlowDefinition, FlowDefinitionVersion]:
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key,
                                                          FlowDefinition.project_id.is_(None)))).scalar_one()
    return flow, await db.get(FlowDefinitionVersion, flow.current_version_id)


async def test_every_published_phase_of_a_to_e_names_its_agent(db):
    for key, phases in EXPECTED.items():
        _flow, version = await _current(db, key)
        nodes = {node["id"]: node for node in version.definition_json["nodes"]}
        assert {node_id: node["config"]["agent"] for node_id, node in nodes.items()
                if node["type"] == "phase"} == phases, key
        assert all("agent" not in dict(node.get("config") or {}).get("sub_agents", {})
                   for node in nodes.values()), key


async def test_an_admin_owned_version_keeps_running_and_gets_the_new_seed_once_as_a_draft(db):
    seed = next(item for item in seed_definitions() if item["key"] == "bug-fix-reproduction")
    flow, current = await _current(db, seed["key"])
    admin_version = {**seed["definition"], "budget": {"tool_calls": 50}}  # an admin's own change
    current.definition_json, current.runtime_settings = admin_version, {}
    version_id = current.id
    await db.flush()
    admin = await admin_user(db)
    assert (await seed_phased_workflows(db, admin_user=admin))["updated"] == 0
    await db.refresh(flow)
    assert flow.current_version_id == version_id
    drafts = (await db.execute(select(FlowDefinitionVersion).where(
        FlowDefinitionVersion.flow_id == flow.id, FlowDefinitionVersion.status == "draft"))).scalars().all()
    assert len(drafts) == 1 and drafts[0].runtime_settings["seed_digest"] == definition_digest(seed["definition"])
    await seed_phased_workflows(db, admin_user=admin)
    again = (await db.execute(select(FlowDefinitionVersion).where(
        FlowDefinitionVersion.flow_id == flow.id, FlowDefinitionVersion.status == "draft"))).scalars().all()
    assert len(again) == 1
