"""Tests for run_agent step tools, stop after steps, and TDD cycle phases."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    _max_iterations_for_agent_step,
    _resolve_allowed_tools_for_step_tool_call,
    run_agent,
)
from app.models import Message, Project, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


def _confluence_step_responses() -> list:
    return [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-search",
                    "function": {
                        "name": "search_confluence",
                        "arguments": '{"query": "report-builder"}',
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
        {
            "content": (
                "No documentation update is required because the existing Report Builder "
                "pages already cover the recent image and configuration changes."
            ),
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
        },
        {
            "content": (
                "No documentation update is required because the existing Report Builder "
                "pages already cover the recent image and configuration changes."
            ),
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16},
        },
    ]


def _confluence_step_agent_definition() -> dict:
    return {
        "name": "Document Updater",
        "steps": [
            {
                "name": "Confluence aktualisieren",
                "step_type": "change",
                "instructions": "Nutze nur die freigegebenen Confluence-Werkzeuge.",
                "success_criteria": "Die betroffenen Seiten wurden aktualisiert oder es gibt eine klare Begruendung, warum keine Aenderung moeglich war.",
                "allowed_tools": [
                    "list_confluence_pages",
                    "get_confluence_page",
                    "update_confluence_page",
                    "create_confluence_page",
                ],
                "isEnabled": True,
            }
        ],
    }


@pytest.mark.asyncio
async def test_run_agent_honors_snake_case_step_allowed_tools(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    observed_tool_names: list[list[str]] = []
    response_queue = _confluence_step_responses()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        observed_tool_names.append([tool["function"]["name"] for tool in (tools or [])])
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        return {"matches": [{"id": "100001", "title": "Report Builder guide"}]}

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    agent_definition = _confluence_step_agent_definition()

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Check whether report-builder docs need an update.",
        user_id=admin.id,
        project_id=project.id,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert observed_tool_names
    assert set(observed_tool_names[0]).issubset(
        {
            "list_confluence_pages",
            "get_confluence_page",
            "update_confluence_page",
            "create_confluence_page",
        }
    )
    assert "run_cli_command" not in observed_tool_names[0]
    assert "prepare_bitbucket_repository" not in observed_tool_names[0]
    assert events[-1].content.startswith("No documentation update is required")


def test_resolve_allowed_tools_for_step_tool_call_advances_to_next_step_scope():
    active_steps = [
        {
            "name": "Read README",
            "allowedTools": ["read_workspace_file"],
        },
        {
            "name": "Write knowledge",
            "allowedTools": ["upsert_project_knowledge"],
        },
    ]

    next_index, next_activity, allowed = _resolve_allowed_tools_for_step_tool_call(
        active_steps=active_steps,
        current_step_index=0,
        current_step_tool_activity=True,
        current_allowed_tool_names={"read_workspace_file"},
        tool_name="upsert_project_knowledge",
    )

    assert next_index == 1
    assert next_activity is False
    assert allowed == {"upsert_project_knowledge"}


def test_max_iterations_for_repository_analysis_steps_is_increased():
    inventory_step = {
        "stepType": "analysis",
        "allowedTools": [
            "list_bitbucket_repositories",
            "prepare_bitbucket_repository",
            "list_repository_readme_status",
        ],
    }
    knowledge_step = {
        "stepType": "knowledge",
        "allowedTools": ["analyze_workspace_repository", "read_workspace_file", "list_workspace_directory"],
    }
    change_step = {
        "stepType": "change",
        "allowedTools": ["upsert_project_knowledge"],
    }
    tdd_step = {
        "stepType": "tdd_cycle",
        "allowedTools": ["run_test_suite", "lint_and_format_workspace", "self_review_workspace_diff"],
    }

    assert _max_iterations_for_agent_step(inventory_step) == 20
    assert _max_iterations_for_agent_step(knowledge_step) == 20
    assert _max_iterations_for_agent_step(change_step) == 8
    assert _max_iterations_for_agent_step(tdd_step) == 24


def test_max_iterations_for_agent_step_respects_explicit_step_config_limit():
    delegated_step = {
        "stepType": "analysis",
        "allowedTools": ["web_search", "web_fetch"],
        "stepConfig": {"max_iterations": 2},
    }

    assert _max_iterations_for_agent_step(delegated_step) == 2


def _readme_builder_agent_definition() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "README Builder",
        "steps": [
            {
                "name": "Knowledge Map erweitern",
                "stepType": "change",
                "instructions": "Store structured knowledge.",
                "successCriteria": "Knowledge entries were updated.",
                "allowedTools": ["upsert_project_knowledge"],
                # The step must call its tool (an allowlist alone does not require one).
                "stepConfig": {"tool_use": "required"},
                "isEnabled": True,
            }
        ],
    }


KNOWLEDGE_MAP_DONE_RESPONSE = {
    "content": "The Knowledge Map update is complete. I have successfully extracted and structured the most important information.",
    "tool_calls": None,
    "model": "claude-haiku-4.5",
    "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
}


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_stops_after_final_step_keeps_skipping_required_tools(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    agent_definition = _readme_builder_agent_definition()

    response_payload = KNOWLEDGE_MAP_DONE_RESPONSE
    response_queue = [dict(response_payload) for _ in range(8)]

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Build README knowledge.",
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    # The tool-required stop is scoped to the step and names its tools.
    assert events[-1].content.startswith(
        "Agent stopped because the step 'Knowledge Map erweitern' must call one of its tools (upsert_project_knowledge)"
    )

    assistant_messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.session_id == session.id, Message.role == "assistant")
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(assistant_messages) == 1
    assert assistant_messages[0].content == events[-1].content
