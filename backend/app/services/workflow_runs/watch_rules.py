"""Publish-time rules of a ``watch`` node."""

from __future__ import annotations

from typing import Any

CLASS_RANK = {"read_only": 0, "change": 1, "deliver": 2}
WATCH_PARAMS = frozenset({"work_state", "job", "workflow", "target"})


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def node_class(node: Any) -> str:
    if node.kind == "phase":
        return str(dict(node.config.get("workflow_contract") or {}).get("capability_class") or "")
    if node.kind == "platform_action":
        from .platform.catalog import action_class

        return action_class(node.config)
    return ""


def _held_before(node: Any, graph: Any) -> int:
    before = graph.order[: graph.order.index(node.id)] if node.id in graph.order else []
    ranks = [CLASS_RANK.get(node_class(graph.nodes[node_id]), -1) for node_id in before]
    return max(ranks, default=0)


def validate_watch(node: Any, graph: Any) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    advance = str(node.config.get("advance") or "confirm")
    if advance not in ("confirm", "auto"):
        errors.append(_error("watch_advance", f"Watch '{node.id}' advance must be confirm or auto."))
    params = node.config.get("params") if node.config.get("params") is not None else {}
    if not isinstance(params, dict) or set(params) - WATCH_PARAMS:
        errors.append(_error("watch_params", f"Watch '{node.id}' params are: {', '.join(sorted(WATCH_PARAMS))}."))
    elif params.get("target") not in (None, "deploy"):
        errors.append(_error("watch_target", f"Watch '{node.id}' target can only be deploy."))
    elif "jira.status" in (node.config.get("conditions") or []) and not str(params.get("work_state") or ""):
        errors.append(_error("watch_work_state", f"Watch '{node.id}' needs the Work state jira.status waits for."))
    if advance == "auto":
        held = _held_before(node, graph)
        for edge in graph.exits(node.id):
            target_class = node_class(graph.nodes[edge.target]) if edge.target in graph.nodes else ""
            rank = CLASS_RANK.get(target_class, -1)
            if target_class == "deliver" or rank > held:
                errors.append(_error(
                    "auto_advance_into_higher_class",
                    f"Watch '{node.id}' cannot advance on its own into '{edge.target}' ({target_class}); "
                    "use advance: confirm."))
    return errors


__all__ = ["CLASS_RANK", "node_class", "validate_watch"]
