"""Step and tool-name checks of an Agent Definition revision snapshot."""

from __future__ import annotations

from typing import Any

from .agent_definition_snapshot import normalize_step_config
from .agent_definition_validation_issues import ValidationIssue

#: Tool name prefixes that ``app.tools.registry.dispatch_tool`` resolves
#: dynamically rather than from ``TOOL_REGISTRY``: generated flow tools, MCP
#: server tools, and admin-defined database query tools. They are accepted as
#: structurally valid because rejecting them would make publication stricter
#: than dispatch; their execution stays gated by ``tool_access_policy`` and
#: ``mcp_access_policy`` at dispatch time. This is an enumerated allowance, not
#: an open-ended fallback: anything outside these prefixes and the registry is
#: an ``unknown_tool`` error.
DYNAMIC_TOOL_PREFIXES: tuple[str, ...] = ("run_flow_", "mcp__", "database_tool_", "rest__")

MAX_STEP_TYPE_LENGTH = 50


def known_tool_names() -> frozenset[str]:
    # The same set the agent builder offers as ``tool_options``, so validation never rejects an offered tool.
    from ..tools.definitions.connector_ownership import SERVICE_ONLY_TOOLS
    from ..tools.registry import TOOL_REGISTRY

    return frozenset(TOOL_REGISTRY.keys() - SERVICE_ONLY_TOOLS)


def is_known_tool(tool_name: str, *, registry_names: frozenset[str]) -> bool:
    name = tool_name.strip()
    if not name:
        return False
    if name in registry_names:
        return True
    return any(name.startswith(prefix) and len(name) > len(prefix) for prefix in DYNAMIC_TOOL_PREFIXES)


def _validate_step_order(steps: list[Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    positions: list[int] = []
    for index, step in enumerate(steps):
        field = f"steps[{index}].position"
        if not isinstance(step, dict):
            issues.append(ValidationIssue("malformed_step", f"steps[{index}]"))
            continue
        position = step.get("position")
        if not isinstance(position, int) or isinstance(position, bool):
            issues.append(ValidationIssue("malformed_step_position", field, str(position)))
            continue
        if position < 1:
            issues.append(ValidationIssue("invalid_step_position", field, str(position)))
            continue
        positions.append(position)

    seen: set[int] = set()
    for position in positions:
        if position in seen:
            issues.append(
                ValidationIssue("duplicate_step_position", "steps", str(position))
            )
        seen.add(position)
    if not issues and sorted(positions) != list(range(1, len(steps) + 1)):
        issues.append(ValidationIssue("non_contiguous_step_positions", "steps"))
    return issues


def _validate_steps(steps: list[Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    registry_names = known_tool_names()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        prefix = f"steps[{index}]"
        if not str(step.get("name") or "").strip():
            issues.append(ValidationIssue("missing_step_name", f"{prefix}.name"))
        step_type = str(step.get("step_type") or "").strip()
        if not step_type:
            issues.append(ValidationIssue("missing_step_type", f"{prefix}.step_type"))
        elif len(step_type) > MAX_STEP_TYPE_LENGTH:
            issues.append(ValidationIssue("step_type_too_long", f"{prefix}.step_type"))

        if normalize_step_config(step.get("step_config")) is None:
            issues.append(
                ValidationIssue("malformed_step_config", f"{prefix}.step_config")
            )

        allowed_tools = step.get("allowed_tools")
        if not isinstance(allowed_tools, list):
            issues.append(
                ValidationIssue("malformed_allowed_tools", f"{prefix}.allowed_tools")
            )
            continue
        for tool in allowed_tools:
            if not isinstance(tool, str) or not is_known_tool(tool, registry_names=registry_names):
                issues.append(
                    ValidationIssue(
                        "unknown_tool",
                        f"{prefix}.allowed_tools",
                        tool if isinstance(tool, str) else type(tool).__name__,
                    )
                )
    return issues
