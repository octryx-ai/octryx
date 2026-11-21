"""A definition's required evidence tools gate its turn before the loop.

Regression case: an AWS topology definition in a Workspace without an active AWS
connector ran, its snapshot calls were denied at dispatch, and it still answered
without evidence. The definition now declares the evidence it cannot answer without;
an unavailable required tool is a closed state before any tool runs, while an optional
connector a definition merely allows never blocks a turn.
"""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Project, Session, ToolCall, User
from app.services.execution_profile_requirements import (
    REASON_CODE_CONNECTOR_INACTIVE,
    REASON_CODE_TOOL_POLICY_DENIED,
    evaluate_workflow_tool_requirements,
)
from app.services.execution_profile_status import (
    EXECUTION_PROFILE_STATUS_DENIED,
    EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION,
)
from app.services.workflow_contracts.registry import build_task_workflow_contract
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

_TOPOLOGY = {
    "workflow_id": "knowledge_request",
    "required_evidence_tools": ["aws_topology_snapshot"],
    "phases": [{"id": "draw", "preferred_tools": ["aws_topology_snapshot", "get_shape_library", "create_diagram"]}],
}


def test_a_required_tool_behind_an_inactive_connector_needs_configuration():
    # The workflow's declared evidence tool is required; available authoring tools do not satisfy it.
    decision = evaluate_workflow_tool_requirements(workflow_contract=_TOPOLOGY, project_config={})

    assert decision.satisfied is False
    assert decision.status == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert decision.reason_code == REASON_CODE_CONNECTOR_INACTIVE
    assert decision.inactive_connectors == ("aws",)
    assert decision.required_tools == ("aws_topology_snapshot",)


def test_an_active_connector_satisfies_the_required_tool():
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=_TOPOLOGY, project_config={"enabled_connectors": ["aws"]}
    )
    assert decision.satisfied is True


def test_an_optional_connector_never_blocks_a_turn():
    optional = {
        "workflow_id": "knowledge_request",
        "phases": [{"id": "collect", "preferred_tools": ["search_jira_tickets", "knowledge_search"]}],
    }
    assert evaluate_workflow_tool_requirements(workflow_contract=optional, project_config={}).satisfied is True


def test_a_required_tool_denied_by_project_policy_is_denied():
    contract = {**_TOPOLOGY, "required_evidence_tools": ["knowledge_search"]}
    decision = evaluate_workflow_tool_requirements(
        workflow_contract=contract, project_config={"tool_policy": {"denylist": ["knowledge_search"]}}
    )
    assert decision.status == EXECUTION_PROFILE_STATUS_DENIED
    assert decision.reason_code == REASON_CODE_TOOL_POLICY_DENIED


def test_the_built_contract_carries_the_definitions_required_tools():
    contract = build_task_workflow_contract(
        "What runs in our AWS account?",
        request_analysis={
            "workflow_contract": {
                "workflow_id": "knowledge_request",
                "required_evidence_tools": ["aws_topology_snapshot"],
            }
        },
    )
    assert contract["required_evidence_tools"] == ["aws_topology_snapshot"]


@pytest.mark.asyncio
async def test_a_topology_turn_without_its_connector_stops_before_the_loop(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"no-aws-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    await db.commit()
    # A workflow-run phase whose inline contract requires the AWS topology evidence.
    resolution = {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_key": "topology-phase",
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "policy_id": None,
        "policy_version_id": None,
        "matched_group_id": None,
        "workflow_contract": {
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request",
            "capability_class": "read_only",
            "required_evidence_tools": ["aws_topology_snapshot"],
        },
        "tool_policy": {"allowlist": ["aws_topology_snapshot", "knowledge_search"]},
        "safety_constraints": {"diagnosis_mode": True, "allow_mutating_tools": False},
    }
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        status="running",
        metadata_={ROUTING_RESOLUTION_KEY: resolution},
    )
    db.add(session)
    await db.commit()

    async def fake_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def no_model_call(**_kwargs):
        raise AssertionError("a turn held for configuration must not call the model")

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", no_model_call)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Draw the topology.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        db=db,
    ):
        pass

    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    assert profile["status"] == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert profile["reason_code"] == REASON_CODE_CONNECTOR_INACTIVE
    tool_calls = (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all()
    assert tool_calls == []
