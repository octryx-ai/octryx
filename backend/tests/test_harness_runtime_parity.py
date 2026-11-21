"""Every ``harness_runtime`` value runs the native loop.

One turn is run through ``run_agent`` twice against the same fake Octryx provider
(no network): once with ``harness_runtime=native``, once with an unrecognized value. The parity
projection below is the contract — both runs must produce it identically:

1. output contract and persisted turn state: yielded events, assistant messages, thread
   context and usage events;
2. tool-call records, on the plain, the approval (pending) and the policy-denial paths;
3. turn traces and trace runs with the frozen ``execution_profile``, the turn execution
   snapshot and the runtime/execution decision-timeline entries;
4. a provider failure: the same ``ProviderRuntimeError`` classification with the same
   ``error_class_source``, the same number of provider calls (no retry or fallback of the
   harness's own) and the same persisted failure record.

Outside the projection by design: the native loop's trace-only planning artifacts (tool
plan contracts, request analysis, working-set notes) and its response-guard quality events.

The runtime half of the boundary is proven here too: a full turn leaves the frameworks absent from
``sys.modules``.
"""

# ruff: noqa: F811  (the shared ``fake_world`` fixture is imported, then requested by name)
from __future__ import annotations

import sys
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.agent.core.runtime.runtime_errors import RUNTIME_ERROR_TRANSIENT, ProviderRuntimeError
from app.agent.engine import run_agent
from app.agent.harness.activation import (
    HARNESS_RUNTIME_NATIVE,
    ConfiguredHarnessRuntime,
    resolve_harness_activation,
)
from app.config import get_settings
from app.models import Message, ThreadContext, ToolCall, TurnTrace, UsageEvent, User
from app.models import Session as AgentSession
from tests.fresh_interpreter_support import run_python_probe
from tests.harness_runtime_support import TOOL, fake_world  # noqa: F401 - fixture
from tests.observability_support import run_summary
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

FINAL_ANSWER = "It is midnight UTC."
TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": TOOL, "arguments": "{}"}}
TOOL_RESPONSE = {"content": "", "tool_calls": [TOOL_CALL], "usage": {"prompt_tokens": 11, "completion_tokens": 3}}
FINAL_RESPONSE = {"content": FINAL_ANSWER, "tool_calls": None, "usage": {"prompt_tokens": 17, "completion_tokens": 5}}
TRANSIENT = ProviderRuntimeError("upstream overloaded", error_class=RUNTIME_ERROR_TRANSIENT)

SCENARIOS: dict[str, tuple[dict[str, Any], list[Any]]] = {
    "tool-then-answer": ({}, [TOOL_RESPONSE, FINAL_RESPONSE]),
    "approval-pending": ({"approval_policy": {"require_for_tools": [TOOL]}}, [TOOL_RESPONSE]),
    "policy-denial": ({"tool_policy": {"denylist": [TOOL]}}, [TOOL_RESPONSE, FINAL_RESPONSE]),
    "provider-failure": ({}, [TRANSIENT, TRANSIENT]),
}
FRAMEWORK_ROOTS = ("pydantic_ai", "pydantic_graph", "genai_prices", "httpx2", "httpcore2", "logfire_api", "truststore")
_VARIABLE_RESULT_KEYS = {"approval_id", "change_preview_id"}


def _framework_modules() -> list[str]:
    return sorted(
        # ``app.agent.harness.runtime`` is the native loop and imports no framework; only the
        # framework distributions count.
        name for name in sys.modules if name.split(".")[0] in FRAMEWORK_ROOTS
    )


async def _run_turn(db, monkeypatch, world, *, runtime: str, scenario: str) -> tuple[str, list[Any]]:
    project_config, script = SCENARIOS[scenario]
    world.update(project_config=project_config, script=list(script), calls=[])
    monkeypatch.setattr(get_settings(), "harness_runtime", runtime)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, agent_type="chat", metadata_=dict(UNDECLARED_READ_ONLY_RUN))
    db.add(session)
    await db.commit()
    events = [
        event
        async for event in run_agent(
            session_id=session.id, user_message="What time is it?", user_id=admin.id, project_id=None,
            agent_type="chat", db=db,
        )
    ]
    await db.commit()
    assert world["script"] == [], "the provider script was not consumed exactly"
    return session.id, events


def _tool_names(calls: list[dict[str, Any]] | None) -> list[str]:
    return [str((call.get("function") or {}).get("name")) for call in calls or []]


def _provider_message(message: dict[str, Any]) -> tuple[Any, ...]:
    """What the provider saw. A tool message embeds its per-run artifact id, so it is compared by call id."""
    if message.get("role") == "tool":
        return ("tool", message.get("tool_call_id"))
    return (message.get("role"), message.get("content"), _tool_names(message.get("tool_calls")))


def _result_projection(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    return {key: ("<id>" if key in _VARIABLE_RESULT_KEYS else value) for key, value in sorted(result.items())}


def _trace_projection(trace: TurnTrace) -> dict[str, Any]:
    context = trace.context_snapshot_json or {}
    snapshot = dict(context.get("turn_execution_snapshot") or {})
    return {
        "provider": trace.provider,
        "model": trace.model,
        "execution_profile": context.get("execution_profile"),
        "turn_execution_snapshot": snapshot,
        "runtime_attempts": [
            {key: attempt.get(key) for key in ("provider", "model", "status", "error_class", "error_class_source",
                                                "retry_decision", "retry_index")}
            for attempt in context.get("runtime_attempts") or []
        ],
        "decisions": [
            (entry.get("phase"), entry.get("title"), entry.get("status"), entry.get("detail"))
            for entry in context.get("decision_timeline") or []
            if entry.get("phase") in {"runtime", "execution"}
        ],
        "tool_trace": [item.get("tool_name") for item in trace.tool_trace_json or []],
    }


async def _parity_projection(db, session_id: str, events: list[Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    async def rows(model, order):
        return (await db.execute(select(model).where(model.session_id == session_id).order_by(order))).scalars().all()

    messages = await rows(Message, Message.created_at)
    tool_calls = await rows(ToolCall, ToolCall.created_at)
    traces = await rows(TurnTrace, TurnTrace.created_at)
    usage = await rows(UsageEvent, UsageEvent.created_at)
    thread = await rows(ThreadContext, ThreadContext.updated_at)
    return {
        "events": [
            (event.role, event.content, _tool_names(event.tool_calls),
             [(item.get("tool_name"), _result_projection(item.get("result"))) for item in event.tool_results or []])
            for event in events
        ],
        "messages": [
            (message.role, message.content, _tool_names(message.tool_calls), message.model, message.tokens_in,
             message.tokens_out)
            for message in messages
        ],
        "tool_calls": [
            (call.tool_name, call.parameters, call.status, _result_projection(call.result)) for call in tool_calls
        ],
        "traces": [_trace_projection(trace) for trace in traces],
        "trace_runs": [((await run_summary(db, trace.id)).outcome, (trace.context_snapshot_json or {}).get("execution_profile"))
                       for trace in traces],
        "usage": [(event.provider, event.model, event.tokens_in, event.tokens_out) for event in usage],
        "thread_context": [row.context_json for row in thread],
        "provider_calls": [
            ([_provider_message(message) for message in call["messages"]], _tool_names(call["tools"])) for call in calls
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_an_unrecognized_harness_setting_runs_the_identical_native_turn(db, monkeypatch, fake_world, scenario: str):
    native_session, native_events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario=scenario)
    native = await _parity_projection(db, native_session, native_events, fake_world["calls"])
    other_session, other_events = await _run_turn(
        db, monkeypatch, fake_world, runtime="unrecognized-runtime", scenario=scenario
    )
    other = await _parity_projection(db, other_session, other_events, fake_world["calls"])

    assert other == native
    assert native["traces"] and all(trace["execution_profile"] for trace in native["traces"])
    assert _framework_modules() == []


@pytest.mark.asyncio
async def test_rollback_flag_off_runs_the_native_loop_without_importing_the_framework(db, monkeypatch, fake_world):
    for name in _framework_modules():
        monkeypatch.delitem(sys.modules, name)
    session_id, events = await _run_turn(
        db, monkeypatch, fake_world, runtime=HARNESS_RUNTIME_NATIVE, scenario="tool-then-answer"
    )
    assert [event.content for event in events if event.role == "assistant"] == [FINAL_ANSWER]
    traces = (await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id))).scalars().all()
    assert traces and not any("harness_runtime" in (trace.context_snapshot_json or {}) for trace in traces)
    assert _framework_modules() == []


def test_importing_the_application_does_not_import_the_framework():
    """Installation alone activates nothing: a fresh interpreter that loads the whole app has no framework module."""
    probe = (
        "import sys, app.main\n"
        f"roots = {FRAMEWORK_ROOTS!r}\n"
        "print(sorted(n for n in sys.modules if n.split('.')[0] in roots))\n"
    )
    completed = run_python_probe(probe)
    assert completed.returncode == 0, "the application import probe failed"
    assert completed.stdout.strip().splitlines()[-1] == "[]"


@pytest.mark.parametrize(
    ("configured", "profile", "agent_definition", "expected"),
    [
        (("", True), {"execution_strategy": "direct"}, None, ("native", "flag_off")),
        (("native", True), {"execution_strategy": "direct"}, None, ("native", "flag_off")),
        (("", False), {"execution_strategy": "direct"}, None, ("native", "flag_unreadable")),
        (("pydantic-ai", True), {"execution_strategy": "direct"}, None, ("native", "flag_unrecognized")),
        (("pydantic_ai", True), {"execution_strategy": "coordinator"}, None, ("native", "flag_unrecognized")),
    ],
)
def test_every_setting_resolves_to_the_native_loop(
    configured, profile, agent_definition, expected
):
    value = ConfiguredHarnessRuntime(value=configured[0], readable=configured[1])
    activation = resolve_harness_activation(
        configured=value, execution_profile=profile, agent_definition=agent_definition
    )
    assert (activation.runtime, activation.reason) == expected
