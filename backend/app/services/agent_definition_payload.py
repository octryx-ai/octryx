"""Execution payload form of an Agent Definition."""

from __future__ import annotations

from typing import Any

from ..models import AgentDefinition, AgentStep
from .agent_definition_types import AgentPayload, AgentStepPayload
from .agent_reply_contract import live_row_reply_contract, snapshot_reply_contract
from .agent_tool_surface_contract import live_row_tool_surface, snapshot_tool_surface
from .prompt_catalog import render_prompt

# A scheduled run of an agent in this mode is enveloped in a coding work item (``secure_work/coding_run``).
CODING_DELIVERY_EXECUTION_MODE = "coding_delivery"
EXECUTION_MODES = frozenset({CODING_DELIVERY_EXECUTION_MODE})


def build_agent_execution_prompt(agent: dict[str, Any]) -> str:
    lines = [
        render_prompt(
            "context.agent.execution_preamble",
            agent_name=agent["name"],
            goal=agent["goal"] or agent["description"] or "-",
        )
    ]
    if agent.get("branchPrefix"):
        lines.append(render_prompt("context.agent.branch_prefix_line", branch_prefix=agent["branchPrefix"]))
    if agent.get("systemPrompt"):
        lines.append(render_prompt("context.agent.execution_notes_line", system_prompt=agent["systemPrompt"]))
    if agent.get("outputPrompt"):
        lines.append(render_prompt("context.agent.output_line", output_prompt=agent["outputPrompt"]))
    active_steps = [step for step in agent.get("steps", []) if step.get("isEnabled")]
    if active_steps:
        lines.append(render_prompt("context.agent.steps_header"))
        for step in active_steps:
            lines.append(
                render_prompt(
                    "context.agent.step",
                    position=step["position"],
                    name=step["name"],
                    step_type=step["stepType"],
                    instructions=step["instructions"] or "-",
                    success_criteria=step["successCriteria"] or "-",
                    allowed_tools=", ".join(step.get("allowedTools") or [])
                    or render_prompt("context.agent.all_tools_label"),
                )
            )
    return "\n".join(lines)


def serialize_agent_step_payload(step: AgentStep) -> AgentStepPayload:
    return {
        "id": step.id,
        "position": step.position,
        "name": step.name,
        "stepType": step.step_type,
        "instructions": step.instructions or "",
        "successCriteria": step.success_criteria or "",
        "allowedTools": step.allowed_tools,
        "stepConfig": step.step_config,
        "isEnabled": bool(step.is_enabled),
    }


def serialize_agent_definition_payload(agent: AgentDefinition) -> AgentPayload:
    payload: AgentPayload = {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description or "",
        "goal": agent.goal or "",
        "agentType": agent.agent_type,
        "thinkingLevel": agent.thinking_level or "light",
        "branchPrefix": agent.branch_prefix or "octryx",
        "requireSelfReview": bool(agent.require_self_review),
        # Verbatim: a persisted invalid value must reach the execution gate, never read as governed.
        "toolSurface": live_row_tool_surface(agent.tool_surface),
        # Text when unset; a stored value verbatim, so an invalid one fails closed at runtime.
        "replyContract": live_row_reply_contract(agent.reply_contract_json),
        "systemPrompt": agent.system_prompt or "",
        "outputPrompt": agent.output_prompt or "",
        "projectId": agent.project_id or "",
        "groupId": agent.group_id or "",
        "groupName": agent.group.name if getattr(agent, "group", None) else "",
        "runtimeTargetId": agent.runtime_target_id or "",
        "skillPreferences": agent.skill_preferences,
        "isActive": bool(agent.is_active),
        "steps": [serialize_agent_step_payload(step) for step in agent.steps],
        "builtinKey": agent.builtin_key or "",
        "capabilityCeiling": agent.capability_ceiling or "read_only",
        "defaultWorkflowKey": agent.default_workflow_key or "",
        "runtimePreference": agent.runtime_preference or "",
        "chatSelectable": bool(agent.chat_selectable),
        "toolsDeny": agent.tools_deny,
    }
    _apply_execution_mode(payload, agent.execution_mode)
    return payload


def payload_from_snapshot(
    snapshot_definition: dict[str, Any],
    snapshot_steps: list[dict[str, Any]],
    *,
    definition_id: str,
    group_name: str = "",
    live_step_ids_by_position: dict[int, str] | None = None,
    builtin_key: str = "",
) -> AgentPayload:
    # A position with no live step yields an empty id: an invented one would resolve to nothing.
    step_ids = live_step_ids_by_position or {}
    payload: AgentPayload = {
        "id": definition_id,
        "name": str(snapshot_definition.get("name") or ""),
        "description": str(snapshot_definition.get("description") or ""),
        "goal": str(snapshot_definition.get("goal") or ""),
        "agentType": str(snapshot_definition.get("agent_type") or ""),
        "thinkingLevel": str(snapshot_definition.get("thinking_level") or "") or "light",
        "branchPrefix": str(snapshot_definition.get("branch_prefix") or "") or "octryx",
        "requireSelfReview": bool(snapshot_definition.get("require_self_review")),
        # Missing means governed; a present value is carried verbatim.
        "toolSurface": snapshot_tool_surface(snapshot_definition),
        # Published mode uses the pinned revision's contract, never the draft's.
        "replyContract": snapshot_reply_contract(snapshot_definition),
        "systemPrompt": str(snapshot_definition.get("system_prompt") or ""),
        "outputPrompt": str(snapshot_definition.get("output_prompt") or ""),
        "projectId": str(snapshot_definition.get("project_id") or ""),
        "groupId": str(snapshot_definition.get("group_id") or ""),
        "groupName": group_name,
        "runtimeTargetId": str(snapshot_definition.get("runtime_target_id") or ""),
        "skillPreferences": snapshot_definition.get("skill_preferences") or {},
        "isActive": bool(snapshot_definition.get("is_active")),
        "steps": [
            _step_payload_from_snapshot(step, step_ids) for step in snapshot_steps
        ],
    }
    payload["builtinKey"] = builtin_key or ""
    payload["capabilityCeiling"] = str(snapshot_definition.get("capability_ceiling") or "read_only")
    payload["defaultWorkflowKey"] = str(snapshot_definition.get("default_workflow_key") or "")
    payload["runtimePreference"] = str(snapshot_definition.get("runtime_preference") or "")
    payload["chatSelectable"] = bool(snapshot_definition.get("chat_selectable"))
    payload["toolsDeny"] = [str(item) for item in snapshot_definition.get("tools_deny") or [] if str(item)]
    _apply_execution_mode(payload, snapshot_definition.get("execution_mode"))
    return payload


def _step_payload_from_snapshot(
    step: dict[str, Any], step_ids_by_position: dict[int, str]
) -> AgentStepPayload:
    position = int(step.get("position") or 0)
    return {
        "id": step_ids_by_position.get(position, ""),
        "position": position,
        "name": str(step.get("name") or ""),
        "stepType": str(step.get("step_type") or ""),
        "instructions": str(step.get("instructions") or ""),
        "successCriteria": str(step.get("success_criteria") or ""),
        "allowedTools": list(step.get("allowed_tools") or []),
        "stepConfig": step.get("step_config") or {},
        "isEnabled": bool(step.get("is_enabled")),
    }


def _apply_execution_mode(payload: AgentPayload, execution_mode: Any) -> None:
    # Never derived from the agent's name.
    mode = str(execution_mode or "").strip()
    if mode in EXECUTION_MODES:
        payload["executionMode"] = mode


__all__ = [
    "CODING_DELIVERY_EXECUTION_MODE",
    "EXECUTION_MODES",
    "build_agent_execution_prompt",
    "payload_from_snapshot",
    "serialize_agent_definition_payload",
    "serialize_agent_step_payload",
]
