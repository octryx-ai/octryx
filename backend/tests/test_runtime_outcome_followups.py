"""The flow-definition branch of ``run_agent`` completes, and agent-step output matches its contract.

- A session that carries ``flow_definition_version_id`` delegates its turn to the flow orchestrator; the
  branch yields a supported assistant event with the run id and status (it must not raise ``TypeError``).
- The flow ``agent_step`` declares ``result`` as the final text (``string``) and an optional ``data``
  object, present only when the agent's checked JSON reply was satisfied; free text is never coerced.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.agent.engine import run_agent
from app.models import OrchestratorAgentRun, Session
from app.services.flow_node_registry import get_flow_node_contract
from app.services.flow_orchestration.runner import execute_flow_version
from app.services.flow_v2_validation import validate_flow_definition_v2
from app.services.run_capability.declared import (
    DECLARED_RUN_CAPABILITY_METADATA_KEY,
    SOURCE_FLOW_DEFINITION,
    declared_run_capability,
)
from tests.flow_agent_step_support import _admin_and_project, _flow, _node_run, _provider_double
from tests.flow_agent_step_support import _agent as _flow_agent

CONTRACT = {
    "kind": "json_object",
    "schema": {"type": "object", "properties": {"total": {"type": "integer"}}, "required": ["total"]},
}
VALID = '{"total": 43}'
TEXT = "The total is 43."


@pytest.mark.asyncio
async def test_a_flow_definition_session_completes_with_a_supported_event(db, monkeypatch):
    admin, project = await _admin_and_project(db)
    agent = await _flow_agent(db, admin.id, project_id=project.id)
    _provider_double(monkeypatch, answer=TEXT)
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Sum."})
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat",
                      status="active", flow_definition_version_id=version.id,
                      # A flow-definition session declares its run capability, as the flow API records it.
                      metadata_={DECLARED_RUN_CAPABILITY_METADATA_KEY: declared_run_capability(
                          None, source=SOURCE_FLOW_DEFINITION).to_metadata()})
    db.add(session)
    await db.commit()

    events = [event async for event in run_agent(
        session_id=session.id, user_message="31, 8, 4", user_id=admin.id, project_id=project.id,
        agent_type="chat", db=db,
    )]

    run = (await db.execute(select(OrchestratorAgentRun).where(
        OrchestratorAgentRun.flow_definition_version_id == version.id))).scalars().one()
    assert [(event.role, event.content) for event in events][-1] == (
        "assistant", f"Workflow run {run.id} ended with status {run.status}.")


def test_the_agent_step_contract_declares_the_final_text_and_optional_data():
    contract = get_flow_node_contract("agent_step")
    assert contract.output_schema == {"result": "string", "data": "object"}
    assert "only when the agent declares a checked" in contract.description


def test_an_existing_flow_mapping_result_still_validates():
    definition = {
        "schema_version": "2.0",
        "nodes": [
            {"id": "start", "type": "trigger", "config": {"trigger_type": "manual"}},
            {"id": "work", "type": "agent_step", "config": {"prompt": "Summarise."}},
            {"id": "end", "type": "output"},
        ],
        "edges": [
            {"source_node_id": "start", "target_node_id": "work"},
            {"source_node_id": "work", "target_node_id": "end", "source_field": "result", "target_field": "result"},
        ],
    }
    report = validate_flow_definition_v2(definition)
    assert not [error for error in report["errors"] if "result" in error.get("message", "")], report["errors"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("checked", "answer", "data"), [
    (True, VALID, {"total": 43}),
    (False, VALID, None),  # a free-text agent's JSON-looking text is never coerced
    (False, TEXT, None),
])
async def test_an_agent_step_exposes_data_only_for_a_satisfied_checked_reply(db, monkeypatch, checked, answer, data):
    admin, project = await _admin_and_project(db)
    agent = await _flow_agent(db, admin.id, project_id=project.id)
    if checked:
        agent.reply_contract_json = json.dumps(CONTRACT)
        await db.flush()
    _provider_double(monkeypatch, answer=answer)
    version = await _flow(db, admin, project.id, {"agent_definition_id": agent.id, "prompt": "Sum."})

    run = await execute_flow_version(
        db, flow_version_id=version.id, project_id=project.id, user_id=admin.id, initial_input={"request": "31, 8, 4"}
    )

    assert run.status == "completed", run.last_error
    output = (await _node_run(db, run, "summarise")).output_json
    assert output["result"] == answer and isinstance(output["result"], str)
    assert output.get("data") == data and (("data" in output) is (data is not None))
