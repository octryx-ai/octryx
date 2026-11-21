"""Explicit step tool-use requirement.

An Incident Triage step with an allowlist was treated as "must call a tool"; a
supplied-facts request that excluded tools got the same reminder context again
and again (six model calls, cancelled by the user). The requirement is now an
explicit step setting (optional without it), and a final step
whose reply declines tools after one reminder ends with an explicit bounded stop.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.core.guards.response_guards import allows_noop_step_completion
from app.agent.core.guards.step_tool_requirement import step_tool_use
from app.agent.loops.response._loop_coding_guard_nudges import CodingGuardInputs
from app.agent.loops.response._loop_response_coding import handle_coding_response_guards
from app.services.prompt_catalog import render_prompt

stop_reasons: list[str | None] = []
suppressed_traces: list[dict] = []

STEP = {
    "name": "Intake the case",
    "stepType": "analysis",
    "instructions": "Collect the minimum evidence needed for triage.",
    "allowedTools": ["search_jira_tickets", "query_loki"],
}
REQUIRED_STEP = {**STEP, "stepConfig": {"tool_use": "required"}}


def test_tool_use_is_explicit_and_an_allowlist_alone_does_not_require_a_tool() -> None:
    assert step_tool_use(STEP) == (False, "default")
    assert step_tool_use(REQUIRED_STEP) == (True, "explicit")
    assert step_tool_use({**STEP, "stepConfig": {"tool_use": "optional"}}) == (False, "explicit")
    assert step_tool_use({"name": "x", "stepConfig": {"tool_use": "required"}}) == (True, "explicit")
    # A typo never relaxes a step.
    assert step_tool_use({**STEP, "stepConfig": {"tool_use": "sometimes"}}) == (True, "invalid_explicit")


class _Db:
    async def commit(self) -> None:
        return None


async def _guard(
    step: dict[str, Any],
    *,
    iterations: int,
    content: str,
    messages: list | None = None,
    active_steps: list | None = None,
):
    persisted: list[str] = []
    stop_reasons.clear()
    suppressed_traces.clear()

    async def persist_turn_trace(**kwargs):
        suppressed_traces.append(kwargs["raw_output"])

    async def persist_traced_assistant_message(**kwargs):
        persisted.append(kwargs["content"])
        stop_reasons.append(kwargs.get("runtime_stop_reason"))

    async def noop(**_kwargs):
        return None

    result = await handle_coding_response_guards(CodingGuardInputs(
        db=_Db(),
        session_id="s",
        runtime={"provider_name": "test"},
        response={"usage": {}},
        request_messages=[],
        messages=messages if messages is not None else [],
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="m",
        content=content,
        tool_calls=None,
        current_step=step,
        current_step_index=(active_steps or [step]).index(step),
        current_step_iterations=iterations,
        current_step_max_iterations=8,
        current_step_tool_activity=False,
        active_steps=active_steps or [step],
        workflow_artifact_ready_for_final_response=False,
        current_turn_content="Summarise these supplied facts in one sentence. Do not use any tools.",
        capability_type="diagnosis",
        tool_context=SimpleNamespace(workspace_root="/tmp/ws"),
        turn_tool_history=[],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        consecutive_coding_no_execution_count=0,
        allows_noop_step_completion=allows_noop_step_completion,
        build_required_tool_reminder=lambda _step: "reminder",
        build_stalled_step_message=lambda _step: "stalled",
        persist_suppressed_runtime_response=noop,
        persist_turn_trace=persist_turn_trace,
        persist_traced_assistant_message=persist_traced_assistant_message,
        _has_meaningful_coding_execution=lambda _history: False,
        _is_probable_coding_change_request=lambda **_kwargs: False,
        _looks_like_coding_intent_only_response=lambda _content: False,
    ))
    return result, persisted


@pytest.mark.asyncio
async def test_a_required_step_reminds_once_then_stops_explicitly_instead_of_looping() -> None:
    answer = "A demo service was down for two minutes, recovered automatically, and affected no users."
    first, _ = await _guard(REQUIRED_STEP, iterations=0, content=answer)
    assert first["action"] == "continue"
    assert len(suppressed_traces) == 1

    second, persisted = await _guard(REQUIRED_STEP, iterations=1, content=answer)
    assert second["action"] == "return"
    expected = "Agent stopped because " + render_prompt(
        "guard.step.tool_required_stop", step_name="Intake the case", tool_names="search_jira_tickets, query_loki"
    )
    assert second["yield_content"] == expected
    assert persisted == [expected]
    # The stop is recorded as the turn's explicit runtime outcome, not left "unknown".
    assert stop_reasons == ["step_tool_required"]
    # One trace per model response: the stop answer's trace is the only record of this call.
    assert suppressed_traces == []
    # The stop does not pass off the untooled reply as the step result.
    assert answer not in expected


@pytest.mark.asyncio
async def test_an_optional_step_lets_a_supplied_facts_answer_through() -> None:
    step = {**STEP, "stepConfig": {"tool_use": "optional"}}
    messages: list = []
    result, persisted = await _guard(
        step, iterations=0, content="One-sentence summary of the supplied facts.", messages=messages
    )
    # No step reminder, no stop: the answer goes on to the normal completion path.
    assert result["action"] == "none"
    assert "reminder" not in [m.get("content") for m in messages]
    assert persisted == []


@pytest.mark.asyncio
async def test_the_stop_after_earlier_steps_claims_nothing_about_the_whole_run() -> None:
    earlier = {"name": "Collect logs", "allowedTools": ["query_loki"]}
    result, _ = await _guard(
        REQUIRED_STEP, iterations=1, content="Summary.", active_steps=[earlier, REQUIRED_STEP]
    )
    assert result["action"] == "return"
    text = result["yield_content"]
    # Scoped to this step: earlier steps may have used tools; no bypass of the agent is suggested.
    assert "earlier steps of this run may already have completed" in text
    assert "Nothing was run" not in text
    assert "without this agent" not in text
