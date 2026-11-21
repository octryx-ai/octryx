"""Flow session IDs honor PostgreSQL's UUID-sized columns and preserve provenance."""

import uuid

import pytest

import app.agent.engine as engine_module
from app.models import FlowDefinition, FlowDefinitionVersion, Project, Session, User
from app.services.flow_orchestration.runner import execute_flow_version


def uid():
    return str(uuid.uuid4())


async def fixture(db):
    user = User(id=uid(), username=f"flow-id-{uid()}", email=f"{uid()}@example.test", password_hash="!")
    project = Project(id=uid(), name="Session identifier acceptance")
    db.add_all([user, project])
    await db.flush()
    flow = FlowDefinition(id=uid(), key=f"identifier-{uid()}", name="Identifier acceptance",
                          project_id=project.id, status="draft", is_active=True, created_by=user.id)
    node_id = "review-" + "long-node-name-" * 7
    # The agent step runs the real agent runtime.
    definition = {
        "schema_version": "2.0",
        "nodes": [{"id": "start", "type": "trigger"},
                  {"id": node_id, "type": "agent_step", "config": {"prompt": "Review the request."}},
                  {"id": "end", "type": "output"}],
        "edges": [{"source_node_id": "start", "target_node_id": node_id},
                  {"source_node_id": node_id, "target_node_id": "end"}],
    }
    version = FlowDefinitionVersion(id=uid(), flow_id=flow.id, version=1, status="draft",
                                    definition_json=definition, created_by=user.id)
    db.add(flow)
    await db.flush()
    db.add(version)
    await db.flush()
    return user, project, version, node_id


@pytest.mark.asyncio
async def test_generated_sessions_are_uuid_sized_independent_and_linked(db, monkeypatch):
    # Provider boundary only (unit test double): the agent runtime itself runs for real.
    async def runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return {"content": "Reviewed.", "tool_calls": None, "model": "claude-haiku-4.5", "usage": {}}, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", chat)
    user, project, version, node_id = await fixture(db)
    runs = [await execute_flow_version(db, flow_version_id=version.id, project_id=project.id,
                                      user_id=user.id, initial_input={"request": "test"}) for _ in range(2)]
    assert runs[0].session_id != runs[1].session_id
    assert runs[0].child_session_ids_json != runs[1].child_session_ids_json
    for run in runs:
        assert run.flow_definition_version_id == version.id
        assert run.project_id == project.id
        assert len(run.session_id) == 36 and str(uuid.UUID(run.session_id)) == run.session_id
        root = await db.get(Session, run.session_id)
        assert (root.user_id, root.project_id, root.flow_definition_version_id) == (user.id, project.id, version.id)
        assert len(run.child_session_ids_json) == 1
        child_id = run.child_session_ids_json[0]
        assert len(child_id) == 36 and str(uuid.UUID(child_id)) == child_id
        child = await db.get(Session, child_id)
        assert (child.user_id, child.project_id, child.parent_session_id) == (user.id, project.id, root.id)
        assert child.flow_definition_version_id == version.id
        assert child.flow_node_id == node_id
        assert child.metadata_["flow_node_id"] == node_id


@pytest.mark.asyncio
async def test_explicit_existing_parent_is_preserved_without_rewriting_it(db):
    user, project, version, _ = await fixture(db)
    parent = Session(id=uid(), user_id=user.id, project_id=project.id,
                     agent_type="diagnosis", metadata_={"existing": True})
    db.add(parent)
    await db.flush()
    run = await execute_flow_version(db, flow_version_id=version.id, parent_session_id=parent.id,
                                     project_id=project.id, user_id=user.id)
    assert run.session_id == parent.id and run.parent_session_id == parent.id
    await db.refresh(parent)
    assert parent.metadata_ == {"existing": True}
    assert parent.flow_definition_version_id is None
    assert parent.agent_type == "diagnosis"
