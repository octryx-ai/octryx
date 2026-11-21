"""run_agent suppresses early completion of a TDD cycle until all phases finish."""

import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Message, Session, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN


def _tdd_agent_definition():
    return {
        "id": str(uuid.uuid4()),
        "name": "TDD Worker",
        "steps": [
            {
                "name": "Implement with TDD",
                "stepType": "tdd_cycle",
                "instructions": "Use a strict red-green-refactor-review loop.",
                "successCriteria": "Tests are green, lint is clean, and self review is ready for PR.",
                "allowedTools": [
                    "run_test_suite",
                    "lint_and_format_workspace",
                    "self_review_workspace_diff",
                    "build_pull_request_description",
                ],
                "isEnabled": True,
            }
        ],
    }


def _tool_call_response(call_id, name, prompt_tokens):
    return {
        "content": "",
        "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": "{}"}}],
        "model": "claude-haiku-4.5",
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 2, "total_tokens": prompt_tokens + 2},
    }


def _text_response(content, prompt_tokens, completion_tokens):
    return {
        "content": content,
        "tool_calls": None,
        "model": "claude-haiku-4.5",
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _early_completion_responses():
    return [
        _tool_call_response("call-tests-red", "run_test_suite", 11),
        _text_response("The TDD cycle is already done.", 12, 4),
        _tool_call_response("call-tests-green", "run_test_suite", 13),
        _tool_call_response("call-lint", "lint_and_format_workspace", 14),
        _tool_call_response("call-review", "self_review_workspace_diff", 15),
        _tool_call_response("call-pr", "build_pull_request_description", 16),
        _text_response("TDD cycle complete and ready for PR.", 17, 5),
    ]


def _tdd_tool_result(tool_name, executed_tools):
    if tool_name == "run_test_suite":
        if executed_tools.count("run_test_suite") == 1:
            return {"framework": "pytest", "failed": 1, "errors": 0, "all_green": False}
        return {"framework": "pytest", "failed": 0, "errors": 0, "all_green": True}
    if tool_name == "lint_and_format_workspace":
        return {"all_clean": True, "failed_checks": [], "checks": []}
    if tool_name == "self_review_workspace_diff":
        return {"ready_for_pr": True, "finding_count": 0, "findings": []}
    if tool_name == "build_pull_request_description":
        return {"markdown": "## Summary\nReady"}
    raise AssertionError(f"Unexpected tool {tool_name}")


def _stub_tdd_runtime(monkeypatch, response_queue, executed_tools):
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return _tdd_tool_result(tool_name, executed_tools)

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_tdd_cycle_suppresses_early_completion_until_all_phases_finish(db, monkeypatch):
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

    agent_definition = _tdd_agent_definition()
    response_queue = _early_completion_responses()

    executed_tools: list[str] = []
    _stub_tdd_runtime(monkeypatch, response_queue, executed_tools)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Implement the refresh fix with a full TDD cycle.",
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert executed_tools == [
        "run_test_suite",
        "run_test_suite",
        "lint_and_format_workspace",
        "self_review_workspace_diff",
        "build_pull_request_description",
    ]
    assert events[-1].content.startswith("TDD cycle complete")

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
    assert all((message.content or "") != "The TDD cycle is already done." for message in assistant_messages)
