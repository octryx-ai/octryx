"""A DAG flow run starts in a Workspace, like a workflow run (``flow_orchestration.start_scope``).

At the public routes a version run, a partial run, a published capability run and a flow test case run without a
Workspace, or with one that does not exist, answer 409 ``needs_configuration`` / ``workspace_required`` before any
session, audit start or run row is written. A member of another Workspace gets for a foreign Workspace exactly the
answer of an unknown one. A capability called as a tool in a chat without a Workspace the caller may start in is the
same typed refusal as a tool result, with nothing written.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, OrchestratorAgentRun, Session
from app.tools.context import ToolContext
from app.tools.flow_capability_dispatch import dispatch_flow_capability_tool
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_inventory import changed, snapshot

pytestmark = pytest.mark.asyncio

FLOWS = "/api/v1/flows"
DEFINITION = {
    "schema_version": "2.0",
    "nodes": [{"id": "input", "type": "trigger", "config": {"trigger_type": "manual"}}, {"id": "out", "type": "output"}],
    "edges": [{"source_node_id": "input", "target_node_id": "out", "source_field": "request", "target_field": "result"}],
}


async def _published_flow(client, headers) -> tuple[str, str, str]:
    """A platform-wide (Workspace-less) flow, published as a capability: its id, version id and tool name."""
    key = f"start-scope-{uuid.uuid4().hex[:8]}"
    created = await client.post(FLOWS, headers=headers, json={"key": key, "name": f"Start {key}",
                                                              "definition": DEFINITION})
    assert created.status_code == 200, created.text
    flow_id, version_id = created.json()["id"], created.json()["versions"][0]["id"]
    published = await client.post(f"{FLOWS}/versions/{version_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    listed = await client.get(f"{FLOWS}/capabilities", headers=headers)
    [tool_name] = [item["tool_name"] for item in listed.json()["items"] if item["flow_key"] == key]
    return flow_id, version_id, tool_name


def _start(action: str, version_id: str, tool_name: str, workspace: dict) -> tuple[str, dict]:
    if action == "run":
        return f"{FLOWS}/versions/{version_id}/run", {"initial_input": {"request": "x"}, **workspace}
    if action == "partial-run":
        return f"{FLOWS}/versions/{version_id}/partial-run", {"node_id": "out", **workspace}
    return f"{FLOWS}/capabilities/{tool_name}/run", {"input": {"request": "x"}, **workspace}


async def _runs(db) -> int:
    return len((await db.execute(select(OrchestratorAgentRun))).scalars().all())


def _typed(response) -> tuple[int, str | None, str | None]:
    detail = response.json().get("detail") or {}
    return response.status_code, detail.get("state"), detail.get("reason")


@pytest.mark.parametrize("action", ["run", "partial-run", "capability"])
@pytest.mark.parametrize("workspace", ["none", "unknown"])
async def test_a_dag_start_without_an_existing_workspace_is_needs_configuration_and_writes_nothing(
        client, db, auth_headers, action, workspace):
    _flow_id, version_id, tool_name = await _published_flow(client, auth_headers)
    await db.commit()
    named = {} if workspace == "none" else {"project_id": str(uuid.uuid4())}
    url, body = _start(action, version_id, tool_name, named)
    before, runs = await snapshot(db), await _runs(db)

    response = await client.post(url, headers=auth_headers, json=body)

    assert _typed(response) == (409, "needs_configuration", "workspace_required"), response.text
    db.expire_all()
    assert changed(before, await snapshot(db)) == [] and await _runs(db) == runs


@pytest.mark.parametrize("action", ["run", "partial-run", "capability"])
async def test_a_dag_start_in_an_existing_workspace_runs_there(client, db, auth_headers, action):
    _flow_id, version_id, tool_name = await _published_flow(client, auth_headers)
    workspace_id = await seed_workspace(db)
    await db.commit()
    url, body = _start(action, version_id, tool_name, {"project_id": workspace_id})

    response = await client.post(url, headers=auth_headers, json=body)

    assert response.status_code == 200, response.text
    payload = response.json()
    run_id = (payload.get("flow_run") or payload["run"])["id"]  # a capability answers its flow run
    assert (await db.get(OrchestratorAgentRun, run_id)).project_id == workspace_id


@pytest.mark.parametrize("action", ["run", "partial-run", "capability"])
async def test_a_member_gets_for_a_foreign_workspace_the_answer_of_an_unknown_one(client, db, auth_headers, action):
    _flow_id, version_id, tool_name = await _published_flow(client, auth_headers)
    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine, role="admin")
    await db.commit()
    answers = []
    for workspace_id in (foreign, str(uuid.uuid4())):
        url, body = _start(action, version_id, tool_name, {"project_id": workspace_id})
        before = await snapshot(db)
        response = await client.post(url, headers=bearer(member), json=body)
        db.expire_all()
        assert changed(before, await snapshot(db)) == []
        answers.append((response.status_code, response.json()["detail"]))
    assert answers[0] == answers[1] and answers[0][0] == 403


@pytest.mark.parametrize("named", ["none", "unknown", "foreign"])
async def test_a_capability_tool_call_without_a_workspace_the_caller_may_start_in_is_refused_typed(
        client, db, auth_headers, named):
    _flow_id, _version_id, tool_name = await _published_flow(client, auth_headers)
    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine, role="member")
    await db.commit()
    project_ids = {"none": [], "unknown": [str(uuid.uuid4())], "foreign": [foreign]}[named]
    session_id = f"capability-{uuid.uuid4().hex[:12]}"
    context = ToolContext(user_id=member, project_ids=project_ids, roles=[], session_id=session_id,
                          project_config={}, db=db, capability_type="change")
    before, runs = await snapshot(db), await _runs(db)

    result = await dispatch_flow_capability_tool(tool_name, {"request": "x"}, context)

    assert (result.get("state"), result.get("reason")) == ("needs_configuration", "workspace_required"), result
    assert await db.get(Session, session_id) is None and await _runs(db) == runs
    started = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow.capability_run_started")))
    assert started.scalars().all() == []
    assert changed(before, await snapshot(db)) == []


async def test_a_test_case_names_an_existing_workspace_and_runs_only_in_one(client, db, auth_headers):
    flow_id, _version_id, _tool_name = await _published_flow(client, auth_headers)
    await db.commit()
    unknown = await client.post(f"{FLOWS}/{flow_id}/test-cases", headers=auth_headers,
                                json={"name": "Unknown", "project_id": str(uuid.uuid4()), "input": {"request": "x"}})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "project_not_found", unknown.text
    created = await client.post(f"{FLOWS}/{flow_id}/test-cases", headers=auth_headers,
                                json={"name": "Without a Workspace", "input": {"request": "x"}})
    assert created.status_code == 200, created.text
    await db.commit()
    before, runs = await snapshot(db), await _runs(db)

    single = await client.post(f"{FLOWS}/{flow_id}/test-cases/{created.json()['id']}/run", headers=auth_headers)
    batch = await client.post(f"{FLOWS}/{flow_id}/test-cases/batch-run", headers=auth_headers, json={})

    for response in (single, batch):
        assert _typed(response) == (409, "needs_configuration", "workspace_required"), response.text
    db.expire_all()
    assert changed(before, await snapshot(db)) == [] and await _runs(db) == runs
