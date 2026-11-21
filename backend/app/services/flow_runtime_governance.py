from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..time_utils import utc_now

DEFAULT_MAX_NODES = 200


class FlowRuntimeLimitExceededError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class FlowRuntimeLimits:
    max_nodes: int
    max_tool_calls: int | None
    max_run_seconds: int | None


@dataclass
class FlowRuntimeUsage:
    started_at: datetime
    tool_calls: int = 0


def resolve_flow_runtime_limits(
    *,
    definition: dict[str, Any],
    version_runtime_settings: dict[str, Any] | None,
    publish_metadata: dict[str, Any] | None = None,
) -> FlowRuntimeLimits:
    merged: dict[str, Any] = {}
    metadata = publish_metadata if isinstance(publish_metadata, dict) else {}
    for source in (
        definition.get("runtime_settings") if isinstance(definition.get("runtime_settings"), dict) else {},
        version_runtime_settings if isinstance(version_runtime_settings, dict) else {},
        metadata.get("budget") if isinstance(metadata.get("budget"), dict) else {},
        metadata.get("budget_limits") if isinstance(metadata.get("budget_limits"), dict) else {},
    ):
        merged.update(source)
    return FlowRuntimeLimits(
        max_nodes=max(1, _optional_int(merged.get("max_nodes")) or DEFAULT_MAX_NODES),
        max_tool_calls=_optional_int(merged.get("max_tool_calls")),
        max_run_seconds=_optional_int(merged.get("max_run_seconds") or merged.get("timeout_seconds")),
    )


def ensure_node_count_within_limits(*, node_count: int, limits: FlowRuntimeLimits) -> None:
    if node_count > limits.max_nodes:
        raise FlowRuntimeLimitExceededError(
            "flow_max_nodes_exceeded",
            f"Flow has {node_count} nodes, above configured max_nodes={limits.max_nodes}.",
            {"node_count": node_count, "max_nodes": limits.max_nodes},
        )


def ensure_run_duration_within_limits(*, usage: FlowRuntimeUsage, limits: FlowRuntimeLimits) -> None:
    if limits.max_run_seconds is None:
        return
    elapsed_seconds = max(0.0, (utc_now() - usage.started_at).total_seconds())
    if elapsed_seconds > limits.max_run_seconds:
        raise FlowRuntimeLimitExceededError(
            "flow_run_timeout_exceeded",
            f"Flow run exceeded configured max_run_seconds={limits.max_run_seconds}.",
            {"elapsed_seconds": elapsed_seconds, "max_run_seconds": limits.max_run_seconds},
        )


def record_tool_call_within_limits(*, usage: FlowRuntimeUsage, limits: FlowRuntimeLimits) -> None:
    usage.tool_calls += 1
    if limits.max_tool_calls is None:
        return
    if usage.tool_calls > limits.max_tool_calls:
        raise FlowRuntimeLimitExceededError(
            "flow_max_tool_calls_exceeded",
            f"Flow run exceeded configured max_tool_calls={limits.max_tool_calls}.",
            {"tool_calls": usage.tool_calls, "max_tool_calls": limits.max_tool_calls},
        )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
