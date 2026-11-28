from __future__ import annotations

import uuid

from sqlalchemy import insert

from app.models import AgentDefinition, FlowDefinition, FlowDefinitionVersion
from tests.policy_engine_support import bearer
from tests.project.private_workspace_resource_support import OWNER_MARKER, insert_run, owner_admin_and_resources
from tests.workspace_id_route_support import answer_text


async def _attention(client, user_id: str) -> str:
    response = await client.get("/api/v1/attention", headers=bearer(user_id))
    assert response.status_code == 200, response.text[:300]
    return response.text


async def test_the_attention_running_feed_leaves_out_a_run_the_caller_requested_in_a_foreign_private_workspace(
        client, db):
    _owner, admin, resources = await owner_admin_and_resources(db)
    own_run = await insert_run(db, resources["shared"].workspace_id, admin.id)
    before = answer_text_without(await _attention(client, admin.id), own_run)
    hidden_run = await insert_run(db, resources["private"].workspace_id, admin.id)
    seen = await _attention(client, admin.id)
    assert own_run in seen
    assert hidden_run not in seen and resources["private"].workspace_id not in seen
    assert answer_text_without(seen, own_run) == before


def answer_text_without(text: str, *ids: str) -> str:
    for item in ids:
        text = text.replace(item, "<id>")
    return text


async def _references(client, user_id: str, agent_id: str):
    return await client.get(f"/admin/chat/api/panel/agents/{agent_id}/references", headers=bearer(user_id))


async def test_the_agents_panel_references_leave_out_a_foreign_private_workflow_that_uses_a_visible_agent(
        client, db):
    owner, admin, resources = await owner_admin_and_resources(db)
    key = f"visible-agent-{uuid.uuid4().hex[:6]}"
    agent = AgentDefinition(name=key, builtin_key=key, project_id=resources["shared"].workspace_id, owner_id=admin.id)
    db.add(agent)
    await db.commit()
    shared_flow = await _flow_using(db, key, resources["shared"].workspace_id, admin.id, "shared")
    with_shared = await _references(client, admin.id, agent.id)
    assert shared_flow in with_shared.text
    hidden_flow = await _flow_using(db, key, resources["private"].workspace_id, owner.id, OWNER_MARKER)
    after = await _references(client, admin.id, agent.id)
    assert hidden_flow not in after.text and OWNER_MARKER not in after.text
    assert answer_text(after, agent.id) == answer_text(with_shared, agent.id)


async def _flow_using(db, agent_key: str, workspace_id: str, creator_id: str, name: str) -> str:
    # A Core insert: the ORM guard keeps workflows out of private Workspaces; the filter must hold on its own.
    flow_id = str(uuid.uuid4())
    await db.execute(insert(FlowDefinition.__table__).values(
        id=flow_id, key=f"{name}-flow-{flow_id[:6]}", name=f"{name} flow {flow_id[:6]}", status="published",
        is_active=True, created_by=creator_id, project_id=workspace_id))
    await db.execute(insert(FlowDefinitionVersion.__table__).values(
        id=str(uuid.uuid4()), flow_id=flow_id, version=1, created_by=creator_id,
        definition_json={"execution_kind": "phased",
                         "nodes": [{"id": "n1", "type": "phase", "config": {"agent": agent_key}}]}))
    await db.commit()
    return flow_id
