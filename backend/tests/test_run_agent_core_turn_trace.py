"""run_agent persists runtime fallback attempts and the turn diff of tool side effects in the turn trace."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import (
    run_agent,
)
from app.models import Session, TurnTrace, User
from tests.run_capability_support import DECLARED_CHANGE_RUN, UNDECLARED_READ_ONLY_RUN


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_persists_runtime_fallback_attempts_in_turn_trace(db, monkeypatch):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        status="running",
        metadata_=dict(UNDECLARED_READ_ONLY_RUN),
    )
    db.add(session)
    await db.commit()

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [
            {
                "provider_name": "openrouter",
                "model": "stepfun/step-3.5-flash:free",
                "target_id": "target-primary",
                "priority": 1,
            },
            {
                "provider_name": "copilot",
                "model": "claude-haiku-4.5",
                "target_id": "target-fallback",
                "priority": 2,
            },
        ]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return (
            {
                "content": "Fallback succeeded",
                "tool_calls": None,
                "model": "claude-haiku-4.5",
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            },
            runtimes[1],
            [
                {
                    "provider": runtimes[0]["provider_name"],
                    "model": runtimes[0]["model"],
                    "target_id": runtimes[0]["target_id"],
                    "priority": runtimes[0]["priority"],
                    "status": "error",
                    "error": "temporary provider outage",
                },
                {
                    "provider": runtimes[1]["provider_name"],
                    "model": runtimes[1]["model"],
                    "target_id": runtimes[1]["target_id"],
                    "priority": runtimes[1]["priority"],
                    "status": "success",
                },
            ],
        )

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)

    async for _event in run_agent(
        session_id=session.id,
        user_message="ping",
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
        runtime_target_id=None,
    ):
        continue

    trace = (
        (
            await db.execute(
                select(TurnTrace).where(TurnTrace.session_id == session.id).order_by(TurnTrace.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert trace is not None
    attempts = trace.raw_output.get("runtime_attempts") or []
    assert len(attempts) == 2
    assert attempts[0]["status"] == "error"
    assert attempts[0]["provider"] == "openrouter"
    assert attempts[1]["status"] == "success"
    assert trace.context_snapshot_json["runtime_attempts"][0]["error"] == "temporary provider outage"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_persists_turn_diff_for_tool_side_effects(db, monkeypatch):
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

    response_queue = [
        {
            "content": "Checking the workspace now.",
            "tool_calls": [
                {
                    "id": "call-bash",
                    "function": {
                        "name": "bash",
                        "arguments": '{"command": "pwd"}',
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
        {
            "content": "Done.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        },
    ]

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    executed_tools: list[str] = []

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        if tool_name != "bash":
            return {"status": "ok"}
        return {
            "command": tool_args["command"],
            "returncode": 0,
            "stdout": "/tmp/workspace\n",
            "stderr": "",
            "output": "/tmp/workspace",
        }

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    async for _event in run_agent(
        session_id=session.id,
        user_message="Inspect the workspace.",
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        db=db,
    ):
        continue

    trace = (
        (
            await db.execute(
                select(TurnTrace).where(TurnTrace.session_id == session.id).order_by(TurnTrace.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert trace is not None
    # A change-mode turn in a workspace without a repository first runs the
    # mode-driven coding preflight (bootstrap, then repository analysis); the model's
    # bash call follows and is the only command side effect.
    assert executed_tools[:2] == ["bootstrap_workspace_repository", "analyze_workspace_repository"]
    assert executed_tools[-1] == "bash"
    assert executed_tools.count("bash") == 1
    turn_diff = trace.context_snapshot_json["turn_diff"]
    assert turn_diff["command_count"] == 1
    assert turn_diff["commands"][0]["tool_name"] == "bash"
    assert turn_diff["commands"][0]["command"] == "pwd"
