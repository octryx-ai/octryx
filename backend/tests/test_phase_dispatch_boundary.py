"""The phase surface is a hard boundary in the real executor.

Without a selected-tool gate in the phase execution-control contract, an injected ``bash pwd`` in Clarify — inside
the read-only capability, outside the phase allowlist — reaches the runtime through ``execute_tool_call_for_turn``.
The executor's call-time gate (before any cache or dispatch) refuses every call outside the phase surface, and an
empty surface refuses every call.
"""

from __future__ import annotations

import uuid

import pytest

from app.agent.core.turn.turn_diff import TurnDiffTracker
from app.agent.core.turn.turn_tools import execute_tool_call_for_turn
from app.tools.context import ToolContext
from app.tools.registry import execute_tool_with_plugins
from tests.shell_expansion_support import _granted_session, _runtime, exec_config  # noqa: F401
from tests.test_phase_tool_gate import _resolution, _server_turn
from tests.test_read_only_security_integration import _state


async def _dispatch(db, monkeypatch, tmp_path, resolution, tool_name: str, arguments: str):
    turn = await _server_turn(resolution)
    _module, calls = _runtime(monkeypatch)
    key = "phase-dispatch-" + uuid.uuid4().hex[:6]
    user = await _granted_session(db, key, "pwd")  # even an approval grant for the exact call never widens a phase
    context = ToolContext(
        user_id=user, project_ids=[], roles=["admin"], session_id="r7-" + key, db=db, capability_type="diagnosis",
        workspace_root=str(tmp_path), project_config={},
        agent_definition={"name": "Engineer", "toolSurface": "governed", "toolsDeny": [], "steps": []},
        run_capability=await _state(db, resolution))
    snapshot = {"tool_execution_control_contract": turn["control"],
                "workflow_contract": resolution["workflow_contract"],
                "request_analysis": {"workflow_contract": resolution["workflow_contract"],
                                     "workflow_routing_policy_resolution": resolution}}
    executed = await execute_tool_call_for_turn(
        db=db, assistant_message_id=str(uuid.uuid4()),
        tool_call={"id": "call-phase", "function": {"name": tool_name, "arguments": arguments}},
        tool_context=context, active_steps=[], current_step_index=0, current_step_tool_activity=False,
        current_allowed_tool_names=set(turn["offered"]), latest_repo_state={},
        infer_repo_tool_args=lambda name, args, state: args,
        resolve_allowed_tools_for_step_tool_call=lambda **kw: (
            kw["current_step_index"], kw["current_step_tool_activity"], kw["current_allowed_tool_names"]),
        compact_tool_result_for_model=lambda name, result: result,
        summary_domains_satisfied_by_result=lambda name, result: set(),
        execute_tool=execute_tool_with_plugins, turn_diff_tracker=TurnDiffTracker(), context_snapshot=snapshot)
    return turn, calls, executed.tool_result


@pytest.mark.asyncio
async def test_clarify_does_not_dispatch_a_bash_read_outside_its_phase_allowlist(db, monkeypatch, tmp_path,
                                                                                exec_config):  # noqa: F811
    turn, calls, result = await _dispatch(db, monkeypatch, tmp_path, _resolution("feature-delivery-tdd", "clarify"),
                                          "bash", '{"command": "pwd"}')

    assert "bash" not in turn["offered"]
    assert calls == []
    assert result["result"]["code"] == "phase_tool_not_offered"


@pytest.mark.asyncio
async def test_an_empty_phase_policy_dispatches_no_injected_call(db, monkeypatch, tmp_path, exec_config):  # noqa: F811
    def drop_policy(node):
        node["config"].pop("tool_policy", None)

    resolution = _resolution("feature-delivery-tdd", "clarify", mutate=drop_policy)
    turn, calls, result = await _dispatch(db, monkeypatch, tmp_path, resolution, "bash", '{"command": "pwd"}')

    assert turn["offered"] == set()
    assert calls == []
    assert result["result"]["code"] == "phase_tool_not_offered"


@pytest.mark.asyncio
async def test_an_offered_clarify_tool_passes_the_phase_gate(db, monkeypatch, tmp_path, exec_config):  # noqa: F811
    (tmp_path / "README.md").write_text("textkit\n", encoding="utf-8")
    _turn, calls, result = await _dispatch(db, monkeypatch, tmp_path, _resolution("feature-delivery-tdd", "clarify"),
                                           "read_workspace_file", '{"path": "README.md"}')

    assert calls == []
    outcome = result["result"]
    assert outcome.get("code") not in {"phase_tool_not_offered", "tool_execution_control_budget_exhausted"}, outcome
    assert "textkit" in str(outcome.get("content") or outcome), outcome
