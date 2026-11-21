"""Shape a runtime response before the guards: workflow override, tool-call repair and evidence enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...core.guards.response_guards import strip_textual_tool_request_preamble
from ...core.runtime.trace_runtime import compact_trace_value
from ._loop_runtime_turn_inputs import RuntimeTurnInputs
from ._loop_textual_tool_repair import audit_text_derived_tool_calls, repair_textual_tool_request


@dataclass
class TurnResponse:
    """The response state the shaping steps rebind in loop order."""

    response: dict[str, Any]
    content: Any
    tool_calls: Any
    context_snapshot: dict[str, Any]
    workflow_contract: Any = None

    def replace_with_tool_calls(self, tool_calls: list[dict[str, Any]]) -> None:
        self.tool_calls = tool_calls
        self.content = ""
        self.response = {**self.response, "content": "", "tool_calls": tool_calls}


def repair_runtime_response(inputs: RuntimeTurnInputs, turn: TurnResponse) -> None:
    allowed = inputs.current_allowed_tool_names
    turn.response, turn.content, turn.tool_calls, turn.context_snapshot, turn.workflow_contract = (
        inputs.apply_workflow_response_override(
            request_analysis=inputs.request_analysis,
            response=turn.response,
            content=turn.content,
            tool_calls=turn.tool_calls,
            turn_tool_history=inputs.turn_tool_history,
            covered_evidence_axes=inputs.covered_evidence_axes,
            current_allowed_tool_names=allowed,
            context_snapshot=turn.context_snapshot,
            runtime_settings=inputs.runtime_settings,
            workflow_contract_from_request_analysis=inputs.workflow_contract_from_request_analysis,
            plan_next_workflow_tool_calls=inputs.plan_next_workflow_tool_calls,
        )
    )
    repaired_tool_calls = repair_textual_tool_request(
        content=turn.content,
        tool_calls=turn.tool_calls,
        context_snapshot=turn.context_snapshot,
        current_allowed_tool_names=allowed,
        capability_type=inputs.capability_type,
    )
    if repaired_tool_calls:
        turn.replace_with_tool_calls(repaired_tool_calls)
    # Text-derived tool calls (provider inline recovery or the loop repair
    # above) are validated against the tool definitions and the turn's
    # authorization set, and audited as `repaired_textual_tool_calls`.
    # Execution stays on the normal dispatch — no gate is bypassed.
    audited_tool_calls = audit_text_derived_tool_calls(
        tool_calls=turn.tool_calls,
        context_snapshot=turn.context_snapshot,
        current_allowed_tool_names=allowed,
        capability_type=inputs.capability_type,
        offered_tool_definitions=inputs.current_tool_definitions,
    )
    if audited_tool_calls is not None:
        turn.tool_calls = audited_tool_calls or None
        turn.response = {**turn.response, "tool_calls": turn.tool_calls}
    if not turn.tool_calls:
        turn.content = strip_textual_tool_request_preamble(turn.content)
        turn.response = {**turn.response, "content": turn.content}


def enforce_evidence_backed_output(inputs: RuntimeTurnInputs, turn: TurnResponse) -> None:
    # Binding evidence rule AFTER textual repair: MiniMax-style inline tool
    # calls only materialize here, so freehand diagram XML from that path must
    # also be swapped for the deterministic evidence render.
    from ..request._loop_evidence_diagrams import enforce_evidence_backed_diagrams

    enforced_diagrams = enforce_evidence_backed_diagrams(
        tool_calls=turn.tool_calls,
        turn_tool_history=inputs.turn_tool_history,
        allowed_tool_names=inputs.current_allowed_tool_names,
    )
    if enforced_diagrams is not None:
        turn.tool_calls, diagram_audit = enforced_diagrams
        turn.response = {**turn.response, "tool_calls": turn.tool_calls}
        turn.context_snapshot["evidence_diagram_enforcement"] = compact_trace_value(
            diagram_audit, trace_limits=inputs.runtime_settings
        )

