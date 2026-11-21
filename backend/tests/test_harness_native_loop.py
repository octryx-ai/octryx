"""The native ``HarnessRuntime`` loop applies request limits, ordered dispatch and correction rules.

The loop rules covered: a request limit counting every model request, tools one at a time in the model's order, one correction per unknown
tool name and one per run for an empty answer, closure errors unchanged. The caller (the governed work item
analysis) turns every run error into ``failed`` /
``agent_runtime_error`` through ``harness_final_text``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent.harness.runtime import (
    HarnessLimitError,
    HarnessPreconditionError,
    HarnessProtocolError,
    HarnessRuntime,
)
from app.services.governed_agent_run.final_text import harness_final_text
from app.services.governed_agent_run.refusals import RunRefusal

ALLOWED = {"status": "allowed"}
BASE = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object"}}}


def _call(call_id: str, name: str, arguments: Any = "{}") -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


class ScriptedModel:
    """Answers each request with the next scripted response and records what it was sent."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    async def __call__(self, messages, tools):
        self.requests.append(([dict(message) for message in messages], tools))
        if not self._responses:
            return {"content": "", "tool_calls": [_call("loop", "lookup")]}
        return self._responses.pop(0)


class RecordingTools:
    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def __call__(self, call):
        self.calls.append(call)
        name = call["function"]["name"]
        if name == self._fail:
            raise RuntimeError("tool backend down")
        return f"result of {name} {call['function']['arguments']}"


def _runtime(model, tools=None, *, definitions=None, request_limit=8, profile=ALLOWED) -> HarnessRuntime:
    return HarnessRuntime(
        execution_profile=profile,
        model_call=model,
        base_messages=BASE,
        tool_definitions=[_tool("lookup"), _tool("search")] if definitions is None else definitions,
        tool_call=tools or RecordingTools(),
        request_limit=request_limit,
    )


@pytest.mark.asyncio
async def test_tools_run_one_at_a_time_in_the_models_order_and_the_text_is_the_answer():
    model = ScriptedModel(
        {"content": "checking", "tool_calls": [_call("a", "search", '{"q": "x"}'), _call("b", "lookup", {"id": 7})]},
        {"content": "done"},
    )
    tools = RecordingTools()
    answer = await _runtime(model, tools).run("task")

    assert answer == "done"
    assert [(call["id"], call["function"]["name"]) for call in tools.calls] == [("a", "search"), ("b", "lookup")]
    # The executor's parsing rule: a JSON string and an already decoded object reach the closure as JSON text.
    assert [json.loads(call["function"]["arguments"]) for call in tools.calls] == [{"q": "x"}, {"id": 7}]
    second_messages, second_tools = model.requests[1]
    assert second_messages[:2] == BASE  # the task is sent once, as the base messages' user turn
    assert [message["role"] for message in second_messages[2:]] == ["assistant", "tool", "tool"]
    assert [message["tool_call_id"] for message in second_messages[3:]] == ["a", "b"]
    assert [definition["function"]["name"] for definition in second_tools] == ["lookup", "search"]


@pytest.mark.asyncio
async def test_a_run_without_tools_offers_none_to_the_model():
    model = ScriptedModel({"content": "verdict"})
    assert await _runtime(model, definitions=[]).run("task") == "verdict"
    assert model.requests[0][1] is None


@pytest.mark.asyncio
async def test_the_request_limit_counts_every_model_request():
    model = ScriptedModel()  # always calls a tool
    tools = RecordingTools()
    with pytest.raises(HarnessLimitError):
        await _runtime(model, tools, request_limit=3).run("task")
    assert len(model.requests) == 3
    assert len(tools.calls) == 3


@pytest.mark.asyncio
async def test_an_unknown_tool_gets_one_correction_and_is_never_dispatched():
    model = ScriptedModel(
        {"content": "", "tool_calls": [_call("u", "delete_all"), _call("k", "lookup")]},
        {"content": "answer"},
    )
    tools = RecordingTools()
    assert await _runtime(model, tools).run("task") == "answer"
    assert [call["function"]["name"] for call in tools.calls] == ["lookup"]
    correction = model.requests[1][0][3]
    assert correction == {
        "role": "tool", "tool_call_id": "u",
        "content": "Unknown tool name: 'delete_all'. Available tools: 'lookup', 'search'\n\nFix the errors and try again.",
    }


@pytest.mark.asyncio
async def test_the_same_unknown_tool_twice_ends_the_run():
    model = ScriptedModel(
        {"content": "", "tool_calls": [_call("u1", "delete_all")]},
        {"content": "", "tool_calls": [_call("u2", "delete_all")]},
        {"content": "never"},
    )
    tools = RecordingTools()
    with pytest.raises(HarnessProtocolError):
        await _runtime(model, tools).run("task")
    assert tools.calls == []
    assert len(model.requests) == 2


@pytest.mark.asyncio
async def test_an_empty_answer_gets_one_correction_per_run():
    model = ScriptedModel({"content": "  "}, {"content": "real answer"})
    assert await _runtime(model).run("task") == "real answer"
    assert model.requests[1][0][-1] == {
        "role": "user",
        "content": "Validation feedback:\nPlease return text or call a tool.\n\nFix the errors and try again.",
    }

    twice = ScriptedModel({"content": ""}, {"content": ""}, {"content": "never"})
    with pytest.raises(HarnessProtocolError):
        await _runtime(twice, definitions=[]).run("task")
    assert twice.requests[1][0][-1]["content"].startswith("Validation feedback:\nPlease return text.")
    assert len(twice.requests) == 2


@pytest.mark.asyncio
async def test_a_tool_error_ends_the_run_unchanged():
    model = ScriptedModel({"content": "", "tool_calls": [_call("a", "search"), _call("b", "lookup")]})
    tools = RecordingTools(fail="search")
    with pytest.raises(RuntimeError, match="tool backend down"):
        await _runtime(model, tools).run("task")
    assert [call["function"]["name"] for call in tools.calls] == ["search"]


def test_a_profile_the_execution_gate_did_not_allow_is_refused():
    with pytest.raises(HarnessPreconditionError):
        _runtime(ScriptedModel(), profile={"status": "blocked"})
    with pytest.raises(HarnessPreconditionError):
        _runtime(ScriptedModel(), profile=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("responses", "fail", "limit"),
    [
        pytest.param([], None, 2, id="request-limit"),
        pytest.param([{"content": ""}, {"content": ""}], None, 8, id="empty-answer"),
        pytest.param([{"content": "", "tool_calls": [_call("a", "search")]}], "search", 8, id="tool-error"),
        pytest.param([{"content": "", "tool_calls": [_call("u", "x")]}, {"content": "", "tool_calls": [_call("v", "x")]}],
                     None, 8, id="unknown-tool"),
    ],
)
async def test_every_run_error_is_agent_runtime_error_for_the_callers(responses, fail, limit):
    """Work Strategy ``agent_step``, the evaluator judge and the governed analysis all settle through this."""
    runtime = _runtime(ScriptedModel(*responses), RecordingTools(fail=fail), request_limit=limit)
    with pytest.raises(RunRefusal) as refusal:
        await harness_final_text(runtime, "task")
    assert (refusal.value.status, refusal.value.error_code) == ("failed", "agent_runtime_error")


@pytest.mark.asyncio
async def test_the_judge_shape_one_request_and_no_tools():
    """The evaluator judge runs with no tools and a request limit of one: a tool call cannot be corrected."""
    model = ScriptedModel({"content": "", "tool_calls": [_call("j", "lookup")]})
    tools = RecordingTools()
    with pytest.raises(RunRefusal):
        await harness_final_text(_runtime(model, tools, definitions=[], request_limit=1), "task")
    assert tools.calls == [] and len(model.requests) == 1
