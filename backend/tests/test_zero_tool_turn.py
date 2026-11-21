"""A selected definition's turn runs with its tools, or stops before the model call.

Regression case: a Workspace-scoped, read-only release-status
definition allowlisting three Jira tools, in a Workspace whose Jira connector was active, ran
with zero tools offered. The context plan withheld tools (``default_standard`` route,
``include_tools=False``) and the explicit workflow tool surface never read the selected
definition's ``tool_policy.allowlist``. Sonnet then wrote fake ```tool_use``` calls as text and
that text went out as the answer.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.agent.loops.response._loop_pseudo_tool_calls import PSEUDO_TOOL_CALL_REFUSAL_REASON
from app.models import (
    BuiltInToolConfig,
    Message,
    Project,
    Session,
    ToolCall,
    TurnTrace,
    User,
)
from app.services.execution_profile_offered_tools import (
    REASON_CODE_DEFINITION_TOOL_UNKNOWN,
    REASON_CODE_DEFINITION_TOOLS_NOT_OFFERED,
)
from app.services.execution_profile_status import EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

_JIRA_TOOLS = ["jira_release_status", "list_jira_versions", "search_jira_tickets"]
_PSEUDO_CALL_ANSWER = (
    "```tool_use\njira_search_issues\n{\n  \"jql\": \"project = OPS\"\n}\n```\n\n"
    "```tool_use\njira_get_project_versions\n{\n  \"project_key\": \"OPS\"\n}\n```"
)


async def _workspace_with_selected_definition(db, *, project_config: dict, jira_tool_config: bool) -> tuple:
    """A Workspace and a running session whose routing resolution is a workflow-run phase."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"w18-{uuid.uuid4().hex[:6]}", config=project_config, is_active=True)
    db.add(project)
    await db.flush()
    if jira_tool_config:
        # The Workspace-scoped connection, as POST /admin/tools/configs/save stores it (no secret needed here).
        db.add(
            BuiltInToolConfig(
                id=str(uuid.uuid4()),
                tool_name="jira",
                project_id=project.id,
                config={
                    "jira_url": "http://127.0.0.1:8096",
                    "jira_email": "stub@example.test",
                    "jira_allowed_projects": ["OPS"],
                },
                is_active=True,
            )
        )
    await db.commit()
    message = "What is the status of OPS release 1.2.0?"
    # A read-only workflow-run phase whose inline definition allowlists three Jira tools.
    resolution = {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_key": f"w18-release-status-{uuid.uuid4().hex[:6]}",
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "policy_id": None,
        "policy_version_id": None,
        "matched_group_id": None,
        "workflow_contract": {
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request",
            "capability_class": "read_only",
        },
        "tool_policy": {"allowlist": list(_JIRA_TOOLS), "denylist": []},
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
    return admin, project, session, message


def _runtimes(monkeypatch, model_calls: list[list[str]], content: str = "OPS 1.2.0 is unreleased.") -> None:
    async def fake_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-5"}]

    async def fake_chat(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None, **_kwargs):
        model_calls.append(sorted(str(tool["function"]["name"]) for tool in tools or []))
        response = {"content": content, "tool_calls": None, "model": "anthropic.claude-sonnet-4-5"}
        return {**response, "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}, runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat)


async def _run(db, admin, project, session, message) -> list[str]:
    contents: list[str] = []
    async for event in run_agent(
        session_id=session.id, user_message=message, user_id=admin.id, project_id=project.id, agent_type="chat", db=db
    ):
        if getattr(event, "role", "") == "assistant" and getattr(event, "content", ""):
            contents.append(str(event.content))
    return contents


@pytest.mark.asyncio
async def test_a_selected_definition_offers_its_allowlisted_workspace_jira_tools(db, monkeypatch):
    admin, project, session, message = await _workspace_with_selected_definition(
        db, project_config={"enabled_connectors": ["jira"]}, jira_tool_config=True
    )
    model_calls: list[list[str]] = []
    _runtimes(monkeypatch, model_calls)

    await _run(db, admin, project, session, message)

    assert model_calls, "the turn must reach the model"
    offered = set(model_calls[0])
    assert set(_JIRA_TOOLS) <= offered, offered
    # The definition's allowlist bounds the surface: nothing outside it (plus the context meta tool).
    assert offered <= {*_JIRA_TOOLS, "instruction_get"}, offered


@pytest.mark.asyncio
async def test_a_definition_whose_tools_cannot_be_offered_needs_configuration_before_the_model(db, monkeypatch):
    # Jira is explicitly deactivated for the Workspace: none of the three tools can be offered.
    admin, project, session, message = await _workspace_with_selected_definition(
        db, project_config={"disabled_connectors": ["jira"]}, jira_tool_config=False
    )
    model_calls: list[list[str]] = []
    _runtimes(monkeypatch, model_calls)

    contents = await _run(db, admin, project, session, message)

    assert model_calls == [], "a turn without its definition's tools must never call the model"
    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    assert profile["status"] == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert profile["reason_code"] == "connector_not_active_for_project"
    assert contents and "jira" in contents[-1].lower()
    tool_calls = (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all()
    assert tool_calls == []


@pytest.mark.asyncio
async def test_a_surface_that_withholds_the_definition_tools_needs_configuration(db, monkeypatch):
    # A surface that withholds every tool (as a keyword plan would for this definition).
    from dataclasses import replace

    import app.agent.core.context.turn_tool_surface as turn_tool_surface_module

    def withholding_surface(plan, **_kwargs):
        return replace(plan, include_tools=False, tool_allowlist=[])

    monkeypatch.setattr(turn_tool_surface_module, "resolve_turn_tool_surface", withholding_surface)
    admin, project, session, message = await _workspace_with_selected_definition(
        db, project_config={"enabled_connectors": ["jira"]}, jira_tool_config=True
    )
    model_calls: list[list[str]] = []
    _runtimes(monkeypatch, model_calls)

    contents = await _run(db, admin, project, session, message)

    assert model_calls == [], "a tool-less definition turn must never reach the model"
    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    assert profile["status"] == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert profile["reason_code"] == REASON_CODE_DEFINITION_TOOLS_NOT_OFFERED
    assert profile["requirements"]["offered_tools"]["withheld_tools"] == _JIRA_TOOLS
    assert contents and "not executed" in contents[-1]


@pytest.mark.asyncio
async def test_a_definition_allowlisting_only_unknown_tools_needs_configuration(db, monkeypatch):
    admin, project, session, message = await _workspace_with_selected_definition(
        db, project_config={"enabled_connectors": ["jira"]}, jira_tool_config=True
    )
    resolution = dict(session.metadata_[ROUTING_RESOLUTION_KEY])
    resolution["tool_policy"] = {"allowlist": ["jira_search_issues", "jira_get_project_versions"]}
    session.metadata_ = {ROUTING_RESOLUTION_KEY: resolution}
    await db.commit()
    model_calls: list[list[str]] = []
    _runtimes(monkeypatch, model_calls)

    await _run(db, admin, project, session, message)

    assert model_calls == []
    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    assert profile["status"] == EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    assert profile["reason_code"] == REASON_CODE_DEFINITION_TOOL_UNKNOWN
    assert profile["requirements"]["offered_tools"]["unknown_tools"] == [
        "jira_get_project_versions",
        "jira_search_issues",
    ]


@pytest.mark.asyncio
async def test_a_pseudo_tool_call_answer_is_not_delivered(db, monkeypatch):
    admin, project, session, message = await _workspace_with_selected_definition(
        db, project_config={"enabled_connectors": ["jira"]}, jira_tool_config=True
    )
    model_calls: list[list[str]] = []
    _runtimes(monkeypatch, model_calls, content=_PSEUDO_CALL_ANSWER)

    contents = await _run(db, admin, project, session, message)

    assert model_calls, "the model is called"
    assert contents, "the turn ends with an explicit message"
    assert len(model_calls) == 2, "tools were offered: one reminder, then the closed refusal"
    assert all("```tool_use" not in content and '"jql"' not in content for content in contents)
    assert "wrote tool calls as text" in contents[-1]
    persisted = (
        await db.execute(select(Message).where(Message.session_id == session.id, Message.role == "assistant"))
    ).scalars().all()
    assert persisted and all("```tool_use" not in str(row.content) for row in persisted)
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session.id))).scalars().all()
    assert [trace.raw_output.get("refusal_reason") for trace in traces if trace.raw_output.get("refusal_reason")] == [
        PSEUDO_TOOL_CALL_REFUSAL_REASON
    ]
    tool_calls = (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all()
    assert tool_calls == []
