"""A phase's ``sub_agents`` configuration: who works the slices and how many at once.

``{"agent": "<built-in key or agent definition id>", "max_parallel": 1..5, "iterations": 1..10}`` — defaults: the
phase's own agent (every phase names one), 5 in parallel, 3 iterations per slice.
Validated at publish.
"""

from __future__ import annotations

from typing import Any

MAX_PARALLEL = 5
DEFAULT_ITERATIONS = 3
MAX_ITERATIONS = 10
KEYS = frozenset({"agent", "max_parallel", "iterations"})


def sub_agent_config(config: dict[str, Any]) -> dict[str, Any] | None:
    raw = config.get("sub_agents")
    if not isinstance(raw, dict):
        return None
    return {"agent": str(raw.get("agent") or config.get("agent") or ""),
            "max_parallel": int(raw.get("max_parallel") or MAX_PARALLEL),
            "iterations": int(raw.get("iterations") or DEFAULT_ITERATIONS)}


def validate_sub_agents(node_id: str, raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    message = (f"Phase '{node_id}': sub_agents takes agent, max_parallel (1-{MAX_PARALLEL}) and iterations "
               f"(1-{MAX_ITERATIONS}).")
    if not isinstance(raw, dict) or set(raw) - KEYS:
        return [{"code": "invalid_sub_agents", "message": message}]
    for key, upper in (("max_parallel", MAX_PARALLEL), ("iterations", MAX_ITERATIONS)):
        value = raw.get(key)
        if value is not None and (type(value) is not int or not 1 <= value <= upper):
            return [{"code": "invalid_sub_agents", "message": message}]
    if raw.get("agent") is not None and not str(raw.get("agent")).strip():
        return [{"code": "invalid_sub_agents", "message": message}]
    return []


__all__ = ["DEFAULT_ITERATIONS", "MAX_PARALLEL", "sub_agent_config", "validate_sub_agents"]
