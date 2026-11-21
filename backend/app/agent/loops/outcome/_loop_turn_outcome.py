"""Turn outcome orchestration after runtime execution."""

from __future__ import annotations

from typing import Any

from ..response._loop_snapshot_reminder import append_snapshot_evidence_reminder
from ._loop_outcome_cycle_inputs import (
    OutcomeCycleInputs,
    no_tool_inputs_from,
    tool_calls_inputs_from,
    tool_followup_inputs_from,
)


async def handle_turn_outcome(inputs: OutcomeCycleInputs) -> dict[str, Any]:
    if not inputs.tool_calls:
        no_tool_flow = await inputs.handle_no_tool_flow(
            no_tool_inputs_from(inputs),
            event_factory=inputs.event_factory,
            maybe_update_summary=inputs.maybe_update_summary,
        )
        return {"kind": "no_tool", **no_tool_flow}

    inputs.context_snapshot.setdefault("request_analysis", inputs.request_analysis)
    inputs.messages.append({"role": "assistant", "content": inputs.content, "tool_calls": inputs.tool_calls})
    tool_execution = await inputs.execute_turn_tool_calls(tool_calls_inputs_from(inputs))
    # Situational reminder: after a successful evidence snapshot create_diagram renders deterministically from it.
    append_snapshot_evidence_reminder(
        messages=inputs.messages,
        tool_results=tool_execution["tool_results"],
        turn_tool_history=tool_execution["turn_tool_history"],
        current_allowed_tool_names=tool_execution["current_allowed_tool_names"],
    )
    tool_followup = await inputs.handle_tool_followup(tool_followup_inputs_from(inputs, tool_execution))
    return {"kind": "tool", "tool_execution": tool_execution, "tool_followup": tool_followup}
