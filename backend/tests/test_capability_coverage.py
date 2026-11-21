"""Every tool-dispatching path carries an explicit run capability.

Chat turns take their class from the selected workflow. The paths that never pick one carry a
declared class instead, and registry dispatch enforces it the same way:

- a flow declares ``capability_class`` on its definition; its tool nodes dispatch under it, and
  the definition is validated like a workflow definition;
- a schedule declares it in its task config; its agent runs, connector steps and validation use it;
- an internal worker takes the class of its explicit worker profile, capped by the run that
  started it;
- ``start_workflow`` never starts anything inside the turn: a code-registry family is an unknown key.

A path that declares nothing runs ``read_only`` and records it as such.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.tools.registry as registry_module
from app.models import User
from app.models.runtime.flow_definition import FlowDefinition, FlowDefinitionVersion
from app.scheduler import TaskScheduler
from app.scheduler.execution._step_connector_execution import execute_connector_action
from app.services.flow_definitions import validate_flow_definition
from app.services.flow_orchestration.runner import execute_flow_version
from app.services.run_capability import resolve_run_capability
from app.services.run_capability.declared import DECLARED_RUN_CAPABILITY_METADATA_KEY
from app.services.run_capability.schedule_capability import (
    require_valid_schedule_capability,
    schedule_session_capability_metadata,
)
from app.services.run_capability.worker_profiles import worker_run_capability, worker_tool_context_state
from app.tools.capability_requirements import tool_required_capability
from app.tools.context import ToolContext
from app.tools.registry import execute_tool
from app.tools.workflow_tools import StartWorkflowTool

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
WRITE_TOOL = "write_workspace_file"


def _context(state: dict | None, **extra) -> ToolContext:
    return ToolContext(
        user_id="u1", project_ids=[], roles=[], session_id="s1", project_config={}, run_capability=state, **extra
    )


def _state(capability_class: str | None, source: str = "test") -> dict:
    return {"class": capability_class, "enforced": True, "source": source, "escalation_decision": None}


@pytest.fixture
def dispatched(monkeypatch):
    """Record what passed every governance gate; nothing real executes."""
    calls: list[str] = []

    async def fake_dispatch(tool_name, params, context):
        calls.append(tool_name)
        return {"ok": True}

    monkeypatch.setattr(registry_module, "_dispatch_registered_tool", fake_dispatch)
    return calls


def _flow(db, suffix: str, capability_class: str | None) -> FlowDefinitionVersion:
    definition = {
        "schema_version": "2.0",
        "nodes": [
            {"id": "input", "type": "trigger"},
            {"id": "write", "type": "tool_step", "config": {"tool": WRITE_TOOL, "arguments": {"path": "a.txt"}}},
            {"id": "out", "type": "output"},
        ],
        "edges": [
            {"source_node_id": "input", "target_node_id": "write"},
            {"source_node_id": "write", "target_node_id": "out"},
        ],
    }
    if capability_class is not None:
        definition["capability_class"] = capability_class
    db.add(FlowDefinition(id=f"f-{suffix}", key=f"cap-{suffix}", name=suffix, status="published", created_by="u1"))
    version = FlowDefinitionVersion(
        id=f"v-{suffix}", flow_id=f"f-{suffix}", version=1, status="published", definition_json=definition,
        created_by="u1",
    )
    db.add(version)
    return version


async def test_a_flow_dispatches_under_its_declared_class_and_is_validated_like_a_definition(db, dispatched):
    undeclared = await execute_flow_version(db, flow_version_id=_flow(db, "none", None).id, user_id="tester")
    assert dispatched == []
    assert undeclared.status == "failed"
    assert undeclared.routing_policy_json["runtime"]["run_capability"] == {
        "class": "read_only",
        "source": "undeclared_read_only",
    }

    declared = await execute_flow_version(db, flow_version_id=_flow(db, "change", "change").id, user_id="tester")
    assert dispatched == [WRITE_TOOL]
    assert declared.routing_policy_json["runtime"]["run_capability"] == {"class": "change", "source": "flow_definition"}

    def capability_errors(definition: dict) -> list[str]:
        report = validate_flow_definition(dict(definition))
        return [error["code"] for error in report["errors"] if "capability_class" in error["code"]]

    change_definition = dict((await db.get(FlowDefinitionVersion, "v-change")).definition_json)
    assert capability_errors((await db.get(FlowDefinitionVersion, "v-none")).definition_json) == [
        "capability_class_exceeded"
    ]
    assert capability_errors(change_definition) == []
    assert capability_errors({**change_definition, "capability_class": "admin"}) == ["unsupported_capability_class"]


async def test_a_schedule_declares_the_class_of_its_agent_runs_and_its_tool_steps(db, dispatched, monkeypatch):
    seen: dict = {}

    async def fake_run_agent(**kwargs):
        seen["session_id"] = kwargs["session_id"]
        return
        yield  # an async generator that emits nothing

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    task = SimpleNamespace(
        id="t1", owner_id=admin.id, project_id=None, agent_type="coding", config={"capability_class": "change"}
    )
    session, _ = await TaskScheduler()._run_agent_for_task(db, task, "go", skip_session_reuse=True)
    metadata = dict(session.metadata_ or {})
    assert metadata[DECLARED_RUN_CAPABILITY_METADATA_KEY] == {"class": "change", "source": "schedule_definition"}

    async def resolved(session_metadata):
        return await resolve_run_capability(
            db, session_metadata=session_metadata, routing_resolution=None, requested_agent_type="coding",
            agent_definition=None, parent_session_id=None,
        )

    change = await resolved(metadata)
    assert (change.capability_class, change.source, change.enforced) == ("change", "schedule_definition", True)
    # A schedule that declares nothing runs read_only (and in its mode), recorded as such.
    undeclared = await resolved(schedule_session_capability_metadata(SimpleNamespace(config={})))
    assert (undeclared.capability_class, undeclared.source, undeclared.enforced) == (
        "read_only", "undeclared_read_only", True,
    )
    assert undeclared.effective_agent_type == "diagnosis"
    broken = await resolved(schedule_session_capability_metadata(SimpleNamespace(config={"capability_class": "root"})))
    assert broken.status == "needs_configuration"

    # A connector step dispatches under the task's class too.
    step = SimpleNamespace(connector_params={"path": "a.txt"}, connector_action=WRITE_TOOL)
    run = SimpleNamespace(id="run-1")
    refused = await execute_connector_action(
        step=step, context={}, db=db, task=SimpleNamespace(**{**vars(task), "config": {}}), task_run=run,
        render_template_params=lambda params, _context: params,
    )
    assert refused["tool_execution"]["policy"] == "run_capability" and dispatched == []
    await execute_connector_action(
        step=step, context={}, db=db, task=task, task_run=run, render_template_params=lambda params, _context: params
    )
    assert dispatched == [WRITE_TOOL]

    # Saving a task or a step validates the declaration against the step tools.
    for config, steps, code in (
        ({"capability_class": "root"}, [], "unsupported_capability_class"),
        ({}, [SimpleNamespace(connector_action=WRITE_TOOL, allowed_tools=[])], "capability_class_exceeded"),
    ):
        with pytest.raises(HTTPException) as refusal:
            require_valid_schedule_capability(config, steps)
        assert [error["code"] for error in refusal.value.detail["errors"]] == [code]
    require_valid_schedule_capability({"capability_class": "change"}, [step])


async def test_a_worker_runs_under_its_profile_capped_by_the_run_that_started_it(dispatched):
    read_only_parent = _context(_state("read_only", "workflow_definition"))
    capped = worker_run_capability("proactive_teams_reply", parent_context=read_only_parent)
    assert (capped.capability_class, capped.capped_by_parent) == ("read_only", True)
    assert worker_run_capability("proactive_teams_reply", parent_context=_context(_state("change"))).capability_class == "change"
    with pytest.raises(ValueError, match="Unregistered worker capability profile"):
        worker_run_capability("anonymous_worker")

    prefetch = _context(worker_tool_context_state("prefetch_worker"))
    refused = await execute_tool(WRITE_TOOL, {"path": "a.txt"}, prefetch)
    assert refused["tool_execution"]["policy"] == "run_capability" and dispatched == []

    # A declaration outside the closed classes dispatches nothing at all.
    refused = await execute_tool("read_workspace_file", {"path": "a.txt"}, _context(_state(None)))
    assert refused["status"] == "needs_configuration" and dispatched == []


async def test_start_workflow_only_proposes_and_never_starts_a_registry_family():
    # The code-registry contract families are no workflows; start_workflow never starts anything.
    tool = StartWorkflowTool()
    params = {"reason": "the user asked for it"}
    for workflow_id in ("generic_document", "coding_change_tdd", "knowledge_request"):
        refused = await tool.execute({**params, "workflow_id": workflow_id}, _context(_state("read_only")))
        assert (refused["status"], refused["reason"]) == ("needs_clarification", "unknown_key")


def test_every_tool_context_in_the_app_carries_a_run_capability_and_workspace_select_is_deliver():
    missing = []
    for path in APP_ROOT.rglob("*.py"):
        if path.name == "context.py" and path.parent.name == "tools":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ToolContext":
                if "run_capability" not in {keyword.arg for keyword in node.keywords}:
                    missing.append(f"{path.relative_to(APP_ROOT)}:{node.lineno}")
    assert missing == []
    # Terraform ``workspace new`` creates state in the remote backend: an external write.
    assert tool_required_capability("workspace_select") == "deliver"
