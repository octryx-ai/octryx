"""Tool policies of a workflow routing resolution: which tools a routed turn may be offered."""

from __future__ import annotations

from typing import Any

from ....services.workflow_routing.tool_policy import (
    expand_tool_policy_allowlist,
    normalized_tool_policy,
    tool_policy_has_rules,
)
from ....services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from ..types import ToolDefinition

INSTRUCTION_META_TOOL = "instruction_get"


def tool_name_of(definition: ToolDefinition) -> str:
    function = definition.get("function") if isinstance(definition, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def unique_tool_names(values: list[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        if value and value not in seen:
            names.append(value)
            seen.add(value)
    return names


def _workflow_contract_tool_names(workflow_contract: dict[str, Any] | None) -> list[str]:
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    source_steps = contract.get("source_steps") if isinstance(contract.get("source_steps"), list) else []
    return list(dict.fromkeys(
        unique_tool_names(
            [
                *(contract.get("allowed_tools") if isinstance(contract.get("allowed_tools"), list) else []),
                *[step.get("tool") for step in source_steps if isinstance(step, dict)],
            ]
        )
    ))


def tool_routing_resolution_for_turn(session_metadata: dict[str, Any]) -> dict[str, Any] | None:
    """The session's routing resolution whose tool policy governs the turn's tool surface."""
    routing_resolution = session_metadata.get(ROUTING_RESOLUTION_KEY)
    return routing_resolution if isinstance(routing_resolution, dict) else None


def routing_tool_policy_from_resolution(
    routing_resolution: dict[str, Any] | None,
) -> dict[str, Any] | None:
    resolution = routing_resolution if isinstance(routing_resolution, dict) else {}
    if resolution.get("source") != "db" or resolution.get("status") != "matched":
        return None
    tool_policy = resolution.get("tool_policy") if isinstance(resolution.get("tool_policy"), dict) else {}
    policy = normalized_tool_policy(tool_policy)
    if not tool_policy_has_rules(policy):
        return None
    if (policy["allowlist"] or policy["allow_patterns"] or policy["allow_read_only"]) and (
        INSTRUCTION_META_TOOL not in policy["allowlist"]
    ):
        policy = {
            **policy,
            "allowlist": [*policy["allowlist"], INSTRUCTION_META_TOOL],
        }
    return {
        "source": "workflow_routing_policy",
        "policy_id": resolution.get("policy_id"),
        "policy_version_id": resolution.get("policy_version_id"),
        "matched_group_id": resolution.get("matched_group_id"),
        "workflow_id": resolution.get("workflow_id"),
        "workflow_class": resolution.get("workflow_class"),
        **policy,
    }


def routing_policy_prefilter_tool_names(
    *,
    routing_resolution: dict[str, Any] | None,
    available_tool_names: list[str],
) -> list[str]:
    resolution = routing_resolution if isinstance(routing_resolution, dict) else {}
    if resolution.get("source") != "db" or resolution.get("status") != "matched":
        return []
    workflow_contract = (
        resolution.get("workflow_contract") if isinstance(resolution.get("workflow_contract"), dict) else {}
    )
    policy = routing_tool_policy_from_resolution(resolution)
    policy_tools: list[str] = []
    if policy is not None:
        policy_tools = expand_tool_policy_allowlist(
            policy,
            available_tool_names=available_tool_names,
            meta_tool_names=[INSTRUCTION_META_TOOL],
        )
    return unique_tool_names([*policy_tools, *_workflow_contract_tool_names(workflow_contract)])


def apply_routing_tool_policy(
    tool_definitions: list[ToolDefinition],
    *,
    routing_resolution: dict[str, Any] | None,
) -> list[ToolDefinition]:
    policy = routing_tool_policy_from_resolution(routing_resolution)
    if policy is None:
        return tool_definitions
    available_tool_names = [tool_name_of(definition) for definition in tool_definitions]
    workflow_contract = (
        routing_resolution.get("workflow_contract")
        if isinstance(routing_resolution.get("workflow_contract"), dict)
        else {}
    )
    allowed_tools = set(
        unique_tool_names(
            [
                *expand_tool_policy_allowlist(
                    policy,
                    available_tool_names=available_tool_names,
                    meta_tool_names=[INSTRUCTION_META_TOOL],
                ),
                *_workflow_contract_tool_names(workflow_contract),
            ]
        )
    )
    filtered: list[ToolDefinition] = []
    for definition in tool_definitions:
        tool_name = tool_name_of(definition)
        if not tool_name:
            continue
        if tool_name not in allowed_tools:
            continue
        filtered.append(definition)
    return filtered
