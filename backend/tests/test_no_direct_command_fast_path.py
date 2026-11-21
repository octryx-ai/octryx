"""No prompt regex turns a chat message into a command.

A turn that offers ``bash`` still goes to the model. Commands run only through the
model's own tool call, and the command tools carry their approval policy.
"""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Message, Session, User
from app.services.prompt_catalog import render_prompt
from app.tools.definitions import get_all_definitions
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


async def _start_turn(db, content: str) -> tuple[User, Session]:
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
    await db.flush()
    user_message = Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content=content)
    db.add(user_message)
    session.metadata_ = {**UNDECLARED_READ_ONLY_RUN, "current_turn_user_message_id": user_message.id}
    await db.commit()
    return admin, session


def _offer_bash(monkeypatch) -> None:
    """Offer ``bash`` the way a selected definition (upgrade, blueprint) would."""
    bash_definition = get_all_definitions()["bash"]
    original_prepare = engine_module._prepare_agent_run

    async def prepare_with_bash(**kwargs):
        prepared = await original_prepare(**kwargs)
        names = {definition.get("function", {}).get("name") for definition in prepared.tool_definitions}
        if "bash" not in names:
            prepared.tool_definitions = [*prepared.tool_definitions, bash_definition]
        return prepared

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare_with_bash)

    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "bedrock", "model": "eu.anthropic.claude-sonnet-4-5"}]

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)


@pytest.mark.asyncio
async def test_command_prompt_reaches_the_model_and_runs_only_through_its_tool_call(db, monkeypatch):
    prompt = "Run python3 manage.py migrate"
    admin, session = await _start_turn(db, prompt)
    _offer_bash(monkeypatch)
    model_calls: list[set[str]] = []
    executed: list[tuple[str, dict]] = []

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        model_calls.append({tool["function"]["name"] for tool in tools or []})
        response = {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-migrate",
                    "function": {"name": "run_cli_command", "arguments": '{"command": "python3 manage.py migrate"}'},
                }
            ],
            "model": runtimes[0]["model"],
            "usage": {},
        }
        return response, runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed.append((tool_name, dict(tool_args)))
        return {
            "error": "Execution blocked by policy: Diagnosis mode requires approval.",
            "tool_name": tool_name,
            "command": tool_args.get("command"),
            "exec_policy_action": "review",
            "approval_required": True,
            "approval_status": "pending",
        }

    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    events = [
        event
        async for event in run_agent(
            session_id=session.id,
            user_message=prompt,
            user_id=admin.id,
            project_id=None,
            agent_type="diagnosis",
            db=db,
        )
    ]

    assert model_calls, "the model decides; no synthesized dispatch replaces it"
    assert "bash" in model_calls[0]
    assert executed == [("run_cli_command", {"command": "python3 manage.py migrate"})]
    assert any(event.role == "tool" for event in events)


@pytest.mark.asyncio
async def test_sub_agent_resume_prompt_does_not_become_a_bash_call(db, monkeypatch):
    admin, session = await _start_turn(db, render_prompt("research.sub_agent_group.waiting"))
    _offer_bash(monkeypatch)
    model_calls: list[set[str]] = []
    executed: list[str] = []

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        model_calls.append({tool["function"]["name"] for tool in tools or []})
        response = {"content": "Consolidated answer.", "tool_calls": [], "model": runtimes[0]["model"], "usage": {}}
        return response, runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed.append(tool_name)
        return {"output": ""}

    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)

    async for _event in run_agent(
        session_id=session.id,
        user_message=render_prompt("research.sub_agent_group.waiting"),
        user_id=admin.id,
        project_id=None,
        agent_type="diagnosis",
        db=db,
    ):
        pass

    assert model_calls
    assert "bash" in model_calls[0]
    assert "bash" not in executed
