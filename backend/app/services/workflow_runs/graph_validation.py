"""The flow validation report of a phased definition: nodes, edges, loops, definition keys and graph-wide rules."""

from __future__ import annotations

from typing import Any

from .graph import (
    EDGE_LOOP,
    EDGE_NEXT,
    EXECUTION_KIND_PHASED,
    NODE_KINDS,
    NODE_OUTCOME,
    NODE_PARALLEL,
    NODE_PHASE,
    NODE_PLATFORM_ACTION,
    NODE_REVIEW,
    NODE_START,
    PhasedEdge,
    PhasedGraph,
    _text,
    _topological_order,
    parse_phased_definition,
    route_values,
)
from .graph_node_rules import _error, _name, _validate_node


def _ancestors(graph: PhasedGraph, node_id: str) -> set[str]:
    seen: set[str] = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        for edge in graph.edges:
            if edge.kind == EDGE_NEXT and edge.target == current and edge.source not in seen:
                seen.add(edge.source)
                stack.append(edge.source)
    return seen


def _arrow(graph: PhasedGraph, edge: PhasedEdge) -> str:
    """An arrow in words: “from “Fix” to “Test””, by the boxes' names."""
    def end(node_id: str) -> str:
        return _name(graph.nodes[node_id]) if node_id in graph.nodes else "a removed box"

    return f"The arrow from {end(edge.source)} to {end(edge.target)}"


def _validate_edges(graph: PhasedGraph) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for edge in graph.edges:
        ids = {"edge_id": edge.id, "node_id": edge.source if edge.source in graph.nodes else None}
        arrow = _arrow(graph, edge)
        if edge.source not in graph.nodes or edge.target not in graph.nodes:
            errors.append(_error("unknown_edge_node", f"{arrow} leads to or from a box that does not exist.", **ids))
            continue
        if edge.kind not in {EDGE_NEXT, EDGE_LOOP}:
            errors.append(_error("edge_kind", f"{arrow} is neither a way on nor a way back.", **ids))
        if edge.kind == EDGE_LOOP:
            if edge.max_iterations is None or edge.max_iterations < 1:
                errors.append(_error("unbounded_loop", f"{arrow} goes back: say how often at most (at least once).",
                                     **ids))
            if edge.target != edge.source and edge.target not in _ancestors(graph, edge.source):
                errors.append(_error("loop_not_back_edge", f"{arrow} is a way back, so it must lead to an earlier "
                                                           "box.", **ids))
        elif edge.max_iterations is not None:
            errors.append(_error("limit_on_next_edge", f"{arrow} is not a way back; only a way back has a maximum.",
                                 **ids))
    for node in graph.nodes.values():
        exits = graph.exits(node.id)
        values = route_values(node, graph)
        name = _name(node)
        if node.kind == NODE_OUTCOME:
            if exits:
                errors.append(_error("outcome_exit", f"{name} ends the workflow, so no arrow may leave it.",
                                     node_id=node.id))
            continue
        if not any(edge.kind == EDGE_NEXT for edge in exits):
            errors.append(_error("dead_end", f"{name} needs an arrow to the next box, so every way reaches an end.",
                                 node_id=node.id))
        seen: set[str | None] = set()
        for edge in exits:
            ids = {"node_id": node.id, "edge_id": edge.id}
            if values is None and edge.when is not None:
                errors.append(_error("unexpected_route", f"{name} has one way out; its arrow needs no result.", **ids))
            if values is not None and edge.when not in values:
                said = f"“{edge.when}”" if edge.when else "no result"
                errors.append(_error("unknown_route", f"{_arrow(graph, edge)} is taken for {said}, which {name} "
                                                      "never has. Choose a result.", **ids))
            if edge.when in seen:
                errors.append(_error("duplicate_route", f"{name} has two arrows for “{edge.when}”.", **ids))
            seen.add(edge.when)
        if values is None and len(exits) > 1:
            # Two ways on from one box would be a static fork the engine never runs; work in parallel is a
            # "Parallel work" box, which splits the work at run time (``teamwork``).
            errors.append(_error("ambiguous_exit", f"{name} has one way out only; remove the extra arrow. To let "
                                                   "agents work side by side, use a “Parallel work” box.",
                                 node_id=node.id))
    return errors


def _push_without_review_errors(graph: PhasedGraph) -> list[dict[str, str]]:
    """A push that agent work reaches without an independent review.

    A run on a device pushes only the change the reviewer reviewed (``platform/scm._reviewed_tree``); a workflow
    without that review validated, then its push failed with a safety stop after all the agent work."""
    start = next((node.id for node in graph.nodes.values() if node.kind == NODE_START), None)
    pushes = {node.id for node in graph.nodes.values()
              if node.kind == NODE_PLATFORM_ACTION and str(node.config.get("action") or "") == "scm.push"}
    if start is None or not pushes:
        return []
    following: dict[str, list[str]] = {}
    for edge in graph.edges:
        following.setdefault(edge.source, []).append(edge.target)
    seen, todo, agent_work = {start}, [start], False
    while todo:
        node = graph.nodes.get(todo.pop())
        if node is None or node.kind == NODE_REVIEW:
            continue
        agent_work = agent_work or node.kind in (NODE_PHASE, NODE_PARALLEL)
        for target in following.get(node.id, []):
            if target not in seen:
                seen.add(target)
                todo.append(target)
    if not agent_work:
        return []
    return [_error("push_without_review", f"{_name(graph.nodes[push])} can be reached without an independent "
                   "review after the agent's work; run on a device (Mac), the push stops there. Add an "
                   "“Independent review” box before it.", node_id=push)
            for push in sorted(pushes & seen)]


def validate_phased_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """The flow validation report of a phased definition."""
    graph = parse_phased_definition(definition)
    errors: list[dict[str, str]] = []
    raw_nodes = [raw for raw in definition.get("nodes") or [] if isinstance(raw, dict)]
    if len({_text(raw.get("id")) for raw in raw_nodes}) != len(raw_nodes):
        errors.append(_error("duplicate_node_id", "Every box needs its own id."))
    errors.extend(_node_kind_errors(graph))
    starts = [node for node in graph.nodes.values() if node.kind == NODE_START]
    if len(starts) != 1:
        errors.append(_error("start_count", "A workflow has exactly one Start box."))
    if not any(node.kind == NODE_OUTCOME for node in graph.nodes.values()):
        errors.append(_error("no_outcome", "A workflow needs at least one End box."))
    errors.extend(_validate_edges(graph))
    errors.extend(_definition_key_errors(definition, graph))
    errors.extend(_graph_rule_errors(graph))
    if _topological_order(graph) is None:
        errors.append(_error("cycle_without_loop_edge", "Arrows go round in a circle. Going back is only allowed "
                                                        "through a way back with a maximum."))
    return {
        "valid": not errors,
        "errors": errors,
        # A warning, not an error: a server run may push without a review; a device run stops at the push.
        "warnings": _push_without_review_errors(graph),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "node_types": sorted({node.kind for node in graph.nodes.values()}),
        "execution_kind": EXECUTION_KIND_PHASED,
    }


def _node_kind_errors(graph: PhasedGraph) -> list[dict[str, str]]:
    """Every node's errors: an unknown kind, an invalid decider, the kind's own rules."""
    errors: list[dict[str, str]] = []
    for node in graph.nodes.values():
        if node.kind not in NODE_KINDS:
            errors.append(_error("unsupported_node_type", f"{_name(node)} is a kind of box this workflow does not "
                                                          f"know ({node.kind}).", node_id=node.id))
            continue
        from .decider import validate_decider_config

        decider_error = validate_decider_config(node.config)
        if decider_error:
            errors.append(_error("decider_invalid", f"{_name(node)}: {decider_error}", node_id=node.id))
        errors.extend(_validate_node(node, graph))
    return errors


def _definition_key_errors(definition: dict[str, Any], graph: PhasedGraph) -> list[dict[str, str]]:
    """The definition's own keys: failure policy, size classes, start triggers, plan node, budget, models."""
    from .failure import validate_failure_policy

    errors = list(validate_failure_policy(definition.get("failure_policy")))
    from .size_class.schema import size_class_errors

    errors.extend(size_class_errors(definition.get("size_classes"), graph))
    from .start_trigger import started_by_errors

    errors.extend(started_by_errors(definition))
    if graph.plan_node and (graph.plan_node not in graph.nodes or graph.nodes[graph.plan_node].kind != NODE_PHASE):
        errors.append(_error("plan_node", "plan_node must name an agent step.",
                             node_id=graph.plan_node if graph.plan_node in graph.nodes else None))
    if "budget" in definition:
        from .limits import BUDGET_KEYS, budget_values

        raw_budget = definition.get("budget")
        if not isinstance(raw_budget, dict) or set(raw_budget) - set(BUDGET_KEYS) or (
                len(budget_values(raw_budget)) != len(raw_budget)):
            errors.append(_error("budget", f"budget takes positive numbers for: {', '.join(BUDGET_KEYS)}."))
    if "models" in definition:
        from .octryx.seat_models import class_models, classes

        raw_models = definition.get("models")
        if not isinstance(raw_models, dict) or class_models(raw_models) != raw_models:
            errors.append(_error("models", f"models maps a model class ({', '.join(classes())}) to a model name."))
    return errors


def _graph_rule_errors(graph: PhasedGraph) -> list[dict[str, str]]:
    """The graph-wide rules: failure routes, deploy approvals, data flow, open high findings, phase agents."""
    from .action_failures import failure_route_errors
    from .data_flow import data_flow_errors
    from .deploy_four_eyes import deploy_approval_errors

    errors = list(failure_route_errors(graph))
    errors.extend(deploy_approval_errors(graph))
    errors.extend(data_flow_errors(graph))
    from .auto_accept import on_open_high_errors

    errors.extend(on_open_high_errors(graph))
    from .phase_agents import static_phase_agent_errors

    errors.extend(static_phase_agent_errors(graph, require=True))  # every phase names its agent
    return errors
