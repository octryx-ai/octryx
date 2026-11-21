"""AWS-specific policy helpers for turn-level tool execution.

Service-owned module: the AWS topology snapshot duplicate guard. Split out of
``app.agent.engine._turn_tools_policy`` (see ``app.services.turn_tool_guards``
for the non-AWS turn tool guards).
"""

from __future__ import annotations

from typing import Any

from ..tools.connectors.aws_topology_common import DEFAULT_TOPOLOGY_SERVICES, KNOWN_TOPOLOGY_SERVICES
from .prompt_catalog import render_prompt
from .turn_tool_guards import _active_guard_rule, _guard_result

_AWS_TOPOLOGY_SNAPSHOT_TOOL = "aws_topology_snapshot"


def aws_topology_snapshot_duplicate_guard_result(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None,
    exec_policy_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    guard_rule = _active_guard_rule(exec_policy_config, "aws_topology_snapshot_already_collected")
    if guard_rule is None:
        return None
    if str(tool_name or "").strip() != _AWS_TOPOLOGY_SNAPSHOT_TOOL:
        return None
    requested = _normalized_topology_services(tool_args)
    if not requested:
        return None

    for item in reversed(turn_tool_history or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() != _AWS_TOPOLOGY_SNAPSHOT_TOOL:
            continue
        result = item.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        prior_services = _topology_services_from_result(result)
        if not prior_services or not requested.issubset(prior_services):
            continue
        return _guard_result({
            "error": render_prompt("tool_guard.aws.topology_duplicate_error"),
            "guardrail": "aws_topology_snapshot_already_collected",
            "requested_services": sorted(requested),
            "covered_services": sorted(prior_services),
            "previous_artifact_id": item.get("artifact_id"),
            "service_summary": result.get("service_summary"),
            "suggested_next_step": render_prompt("tool_guard.aws.topology_duplicate_next_step"),
        }, guard_rule)
    return None


def _normalized_topology_services(tool_args: dict[str, Any]) -> set[str]:
    raw_services = tool_args.get("services") if isinstance(tool_args, dict) else None
    if not raw_services:
        return set(DEFAULT_TOPOLOGY_SERVICES)
    if isinstance(raw_services, str):
        candidates = [raw_services]
    elif isinstance(raw_services, list):
        candidates = raw_services
    else:
        return set(DEFAULT_TOPOLOGY_SERVICES)
    services = {
        str(item).strip().lower().replace("_", "-")
        for item in candidates
        if str(item or "").strip().lower().replace("_", "-") in KNOWN_TOPOLOGY_SERVICES
    }
    return services or set(DEFAULT_TOPOLOGY_SERVICES)


def _topology_services_from_result(result: dict[str, Any]) -> set[str]:
    scope = result.get("scope") if isinstance(result.get("scope"), dict) else {}
    summary = result.get("service_summary") if isinstance(result.get("service_summary"), dict) else {}
    raw_services = scope.get("services_requested") or summary.get("services_requested") or []
    if not isinstance(raw_services, list):
        return set()
    services = {
        str(item).strip().lower().replace("_", "-")
        for item in raw_services
        if str(item or "").strip().lower().replace("_", "-") in KNOWN_TOPOLOGY_SERVICES
    }
    return services


__all__ = ["aws_topology_snapshot_duplicate_guard_result"]
