"""Tests for run_agent step planning: the required self-review step of change agents.

A turn keeps its resolved runtime for every iteration.
"""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Session, User
from tests.run_capability_support import DECLARED_CHANGE_RUN


def _self_review_change_agent_definition() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "Change Agent",
        "requireSelfReview": True,
        "steps": [
            {
                "name": "Implement",
                "stepType": "change",
                "instructions": "Make the requested change.",
                "successCriteria": "The change is complete.",
                "allowedTools": [],
                "isEnabled": True,
            }
        ],
    }


def _self_review_change_responses() -> list:
    return [
        {
            "content": "Implementation is complete.",
            "tool_calls": None,
            "model": "general-model-v1",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        },
        {
            "content": "",
            "tool_calls": [
                {"id": "call-review", "function": {"name": "self_review_workspace_diff", "arguments": "{}"}}
            ],
            "model": "general-model-v1",
            "usage": {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13},
        },
        {
            "content": "",
            "tool_calls": [
                {"id": "call-pr", "function": {"name": "build_pull_request_description", "arguments": "{}"}}
            ],
            "model": "general-model-v1",
            "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14},
        },
        {
            "content": "Change flow completed after self review.",
            "tool_calls": None,
            "model": "general-model-v1",
            "usage": {"prompt_tokens": 13, "completion_tokens": 4, "total_tokens": 17},
        },
    ]


@pytest.mark.asyncio
async def test_run_agent_appends_required_self_review_step_for_change_agents(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        status="running",
        metadata_=dict(DECLARED_CHANGE_RUN),
    )
    db.add(session)
    await db.commit()

    agent_definition = _self_review_change_agent_definition()

    observed_step_prompts: list[str] = []
    response_queue = _self_review_change_responses()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "openrouter", "model": "general-model-v1"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        for message in reversed(messages):
            if message.get("role") == "system" and "Current step:" in str(message.get("content") or ""):
                observed_step_prompts.append(str(message.get("content") or ""))
                break
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        if tool_name == "self_review_workspace_diff":
            return {"ready_for_pr": True, "finding_count": 0, "findings": []}
        if tool_name == "build_pull_request_description":
            return {"markdown": "## Summary\nReady"}
        raise AssertionError(f"Unexpected tool {tool_name}")

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Apply the requested code change.",
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert any("Self Review" in prompt for prompt in observed_step_prompts)
    assert any(
        (event.content or "").startswith("Change flow completed after self review.")
        for event in events
        if event.role == "assistant"
    )
