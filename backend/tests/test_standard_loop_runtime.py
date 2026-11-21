import pytest

from app.agent.core.runtime._standard_loop_runtime import stream_standard_loop_iterations


async def _emit_loop_final_fallback(**kwargs):  # type: ignore[no-untyped-def]
    return kwargs["event_factory"](role="assistant", content="[fallback]")


def _event_factory(**kwargs):  # type: ignore[no-untyped-def]
    return kwargs


@pytest.mark.asyncio
async def test_standard_loop_extends_knowledge_iterations_only_while_evidence_progresses():
    state = {
        "request_messages": [{"role": "user", "content": "what can you tell me about Report Builder?"}],
        "turn_tool_history": [
            {
                "tool_name": "knowledge_read",
                "params": {"evidence_key": "report-builder-1"},
                "result": {"content": "initial evidence"},
            }
        ],
        "executed_tool_names": {"knowledge_read"},
        "workflow_contract": {"workflow_id": "knowledge_request"},
        "messages": [],
        "total_tokens_in": 0,
        "total_tokens_out": 0,
    }
    iterations: list[int] = []

    async def _run_standard_loop_iteration(**kwargs):  # type: ignore[no-untyped-def]
        iteration = kwargs["iteration"]
        iterations.append(iteration)
        state["turn_tool_history"].append(
            {
                "tool_name": "knowledge_read",
                "params": {"evidence_key": f"report-builder-{iteration + 2}"},
                "result": {"content": "new evidence"},
            }
        )
        return {"action": "continue", "events": []}

    events = [
        event
        async for event in stream_standard_loop_iterations(
            max_iterations=2,
            state=state,
            runtime_settings={},
            max_iterations_for_agent_step=lambda step: 8,
            runtime_cycle_shared={},
            outcome_cycle_shared={},
            summary_domains_for_result=lambda tool_name, result: set(),
            run_standard_loop_iteration=_run_standard_loop_iteration,
            emit_loop_final_fallback=_emit_loop_final_fallback,
            db=None,
            session_id="session-1",
            event_factory=_event_factory,
            build_runtime_error_salvage_message=lambda **kwargs: "",
        )
    ]

    assert len(iterations) == 10
    assert state["knowledge_iteration_extension_count"] == 8
    assert state["final_iteration_instruction_added"] is True
    assert events[-1]["content"] == "[fallback]"


@pytest.mark.asyncio
async def test_standard_loop_does_not_extend_non_knowledge_iterations():
    state = {
        "request_messages": [{"role": "user", "content": "hello"}],
        "turn_tool_history": [{"tool_name": "web_search", "params": {"query": "x"}, "result": {"count": 1}}],
        "executed_tool_names": {"web_search"},
        "workflow_contract": None,
        "messages": [],
        "total_tokens_in": 0,
        "total_tokens_out": 0,
    }
    iterations: list[int] = []

    async def _run_standard_loop_iteration(**kwargs):  # type: ignore[no-untyped-def]
        iterations.append(kwargs["iteration"])
        return {"action": "continue", "events": []}

    events = [
        event
        async for event in stream_standard_loop_iterations(
            max_iterations=2,
            state=state,
            runtime_settings={},
            max_iterations_for_agent_step=lambda step: 8,
            runtime_cycle_shared={},
            outcome_cycle_shared={},
            summary_domains_for_result=lambda tool_name, result: set(),
            run_standard_loop_iteration=_run_standard_loop_iteration,
            emit_loop_final_fallback=_emit_loop_final_fallback,
            db=None,
            session_id="session-1",
            event_factory=_event_factory,
            build_runtime_error_salvage_message=lambda **kwargs: "",
        )
    ]

    assert iterations == [0, 1]
    assert state["final_iteration_instruction_added"] is True
    assert events[-1]["content"] == "[fallback]"
