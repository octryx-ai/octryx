"""run_agent honors custom TDD phases and resumes them from the thread context."""

import copy
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import run_agent
from app.models import Session, ThreadContext, User
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

_CUSTOM_TDD_PHASES = [
    {
        "name": "write_tests",
        "title": "Write Tests",
        "instructions": "tests first",
        "completion_rule": "tool_called",
        "required_tools": ["run_test_suite"],
    },
    {
        "name": "make_green",
        "title": "Make Green",
        "instructions": "green",
        "completion_rule": "test_green",
        "required_tools": ["run_test_suite"],
    },
    {
        "name": "security_review",
        "title": "Security Review",
        "instructions": "run sast",
        "completion_rule": "sast_clean",
        "required_tools": ["run_sast_suite"],
    },
    {
        "name": "self_review",
        "title": "Self Review",
        "instructions": "review",
        "completion_rule": "review_ready",
        "required_tools": ["self_review_workspace_diff", "build_pull_request_description"],
    },
]


def _tool_response(call_id, tool_name, prompt_tokens):
    return {
        "content": "",
        "tool_calls": [{"id": call_id, "function": {"name": tool_name, "arguments": "{}"}}],
        "model": "general-model-v1",
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 2, "total_tokens": prompt_tokens + 2},
    }


async def _seed_session_resuming_at_make_green(db):
    """A change session whose thread context already finished write_tests (phase index 1 of the custom phases)."""
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
    db.add(
        ThreadContext(
            session_id=session.id,
            version=1,
            derived_from_message_id=None,
            context_json={
                "tdd_cycle": {
                    "phase_index": 1,
                    "phases": copy.deepcopy(_CUSTOM_TDD_PHASES),
                    "phase_tool_counts": {"write_tests": {"run_test_suite": 1}},
                    "phase_results": {"write_tests": {"run_test_suite": {"all_green": False}}},
                    "history": [
                        {"phase": "write_tests", "tool_name": "run_test_suite", "result": {"all_green": False}}
                    ],
                }
            },
        )
    )
    await db.commit()
    return admin, session


def _custom_tdd_agent_definition():
    return {
        "id": str(uuid.uuid4()),
        "name": "Custom TDD Worker",
        "steps": [
            {
                "name": "Implement with custom TDD",
                "stepType": "tdd_cycle",
                "instructions": "Use a custom red-green-security-review loop.",
                "successCriteria": "Green, secure, and reviewed.",
                "allowedTools": [
                    "run_test_suite",
                    "run_sast_suite",
                    "self_review_workspace_diff",
                    "build_pull_request_description",
                ],
                "stepConfig": {
                    "tdd_cycle_phases": [
                        "write_tests",
                        "make_green",
                        "security_review",
                        "self_review",
                    ]
                },
                "isEnabled": True,
            }
        ],
    }


def _stub_runtime_and_tools(monkeypatch, response_queue, observed_step_prompts, executed_tools):
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "openrouter", "model": "general-model-v1"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        for message in reversed(messages):
            if message.get("role") == "system" and "Current step:" in str(message.get("content") or ""):
                observed_step_prompts.append(str(message.get("content") or ""))
                break
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        if tool_name == "run_test_suite":
            return {"framework": "pytest", "failed": 0, "errors": 0, "all_green": True}
        if tool_name == "run_sast_suite":
            return {"all_clean": True, "failed_checks": [], "checks": []}
        if tool_name == "self_review_workspace_diff":
            return {"ready_for_pr": True, "finding_count": 0, "findings": []}
        if tool_name == "build_pull_request_description":
            return {"markdown": "## Summary\nReady"}
        raise AssertionError(f"Unexpected tool {tool_name}")

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_run_agent_tdd_cycle_honors_custom_phases_and_resumes_from_thread_context(db, monkeypatch):
    admin, session = await _seed_session_resuming_at_make_green(db)
    agent_definition = _custom_tdd_agent_definition()

    observed_step_prompts: list[str] = []
    executed_tools: list[str] = []
    response_queue = [
        _tool_response("call-tests-green", "run_test_suite", 12),
        _tool_response("call-sast", "run_sast_suite", 13),
        _tool_response("call-review", "self_review_workspace_diff", 14),
        _tool_response("call-pr", "build_pull_request_description", 15),
        {
            "content": "Custom TDD cycle complete.",
            "tool_calls": None,
            "model": "general-model-v1",
            "usage": {"prompt_tokens": 16, "completion_tokens": 4, "total_tokens": 20},
        },
    ]
    _stub_runtime_and_tools(monkeypatch, response_queue, observed_step_prompts, executed_tools)

    events = []
    async for event in run_agent(
        session_id=session.id,
        user_message="Finish the change with custom TDD phases.",
        user_id=admin.id,
        project_id=None,
        agent_type="change",
        db=db,
        agent_definition=agent_definition,
    ):
        events.append(event)

    assert executed_tools == [
        "run_test_suite",
        "run_sast_suite",
        "self_review_workspace_diff",
        "build_pull_request_description",
    ]
    assert any("Current TDD phase: 2/4 - Make Green" in prompt for prompt in observed_step_prompts)
    assert any("Current TDD phase: 3/4 - Security Review" in prompt for prompt in observed_step_prompts)
    context_row = (await db.execute(select(ThreadContext).where(ThreadContext.session_id == session.id))).scalar_one()
    assert context_row.context_json["tdd_cycle"]["history"][-1]["tool_name"] == "build_pull_request_description"
    assert events[-1].content == "Custom TDD cycle complete."
