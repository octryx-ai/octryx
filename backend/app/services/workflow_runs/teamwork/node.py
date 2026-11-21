"""The ``parallel_work`` node's configuration and its publish validation (design section 3).

``{"plan": "<phase id>", "roles": {"<role>": <phase template>}, "parallel": true}``:

- ``plan``: the phase before this node whose ``output`` is ``work_plan``; ``replan`` must be a way back to it.
- ``roles``: what each role's item session runs as — an ordinary phase definition (``agent``, optional ``model``,
  ``workflow_contract`` with its capability class and done criteria, ``tool_policy``; optional ``needs_proof:
  false`` for a role whose items prove nothing with a test; optional ``starts_at_once: true`` for a role whose items
  build from the contract and never wait for other items, the test role: its tests run on the merged story in the
  pipeline). Each is validated exactly like a phase; the item's own paths become its ``path_rules.write`` at run time.
- ``parallel: false``: the items still run one at a time with their own sessions and models (sequential).
"""

from __future__ import annotations

import re
from typing import Any

from .. import graph as graph_module
from .. import graph_node_rules, graph_validation
from . import OUTPUT_KIND, ROUTE_DONE, ROUTE_REPLAN

ROLE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
CONFIG_KEYS = frozenset({"plan", "roles", "parallel", "title", "description", "layout", "decider"})


def plan_node_id(node: Any) -> str:
    return str(dict(node.config or {}).get("plan") or "").strip()


def roles_of(node: Any) -> dict[str, dict[str, Any]]:
    raw = dict(node.config or {}).get("roles")
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)} if isinstance(
        raw, dict) else {}


def runs_parallel(node: Any) -> bool:
    return dict(node.config or {}).get("parallel") is not False


def role_node(node: Any, role: str) -> Any:
    """A role template as the phase node it is validated (and later run) as."""
    template = roles_of(node).get(role) or {}
    return graph_module.PhasedNode(node.id, graph_module.NODE_PHASE, f"{node.title} · {role}", dict(template))


def parallel_node_errors(node: Any, graph: Any) -> list[dict[str, str]]:
    from ..phase_agents import static_phase_agent_errors

    name = graph_node_rules._name(node)
    errors: list[dict[str, str]] = []
    plan = plan_node_id(node)
    plan_node = graph.nodes.get(plan) if plan else None
    if plan_node is None or plan_node.kind != graph_module.NODE_PHASE or str(
            plan_node.config.get("output") or "") != OUTPUT_KIND:
        errors.append(graph_node_rules._error("parallel_plan", f"{name}: choose the agent step that plans the work "
                                                           f"(its output is the work plan, {OUTPUT_KIND})."))
    elif plan not in graph_validation._ancestors(graph, node.id):
        errors.append(graph_node_rules._error("parallel_plan", f"{name}: the step that plans the work must come "
                                                           "before it."))
    raw_roles = node.config.get("roles")
    if not isinstance(raw_roles, dict) or not raw_roles:
        errors.append(graph_node_rules._error("parallel_roles", f"{name}: name at least one role (backend, frontend, "
                                                            "test, ...) and what it runs as."))
        raw_roles = {}
    for role, template in raw_roles.items():
        if not ROLE_NAME.match(str(role)) or not isinstance(template, dict):
            errors.append(graph_node_rules._error("parallel_roles", f"{name}: role {role!r} is a lower-case name with "
                                                                "its agent step definition."))
            continue
        for flag in ("needs_proof", "starts_at_once"):
            if flag in template and template[flag] not in (True, False):
                errors.append(graph_node_rules._error("parallel_roles", f"{name}: {flag} of role {role!r} is on or "
                                                                    "off."))
        synthetic = role_node(node, str(role))
        role_graph = graph_module.PhasedGraph(nodes={synthetic.id: synthetic}, edges=[])
        found = graph_node_rules._validate_phase(synthetic) + static_phase_agent_errors(role_graph, require=True)
        errors += [{**item, "message": f"Role {role!r}: {item['message']}"} for item in found]
    if "parallel" in node.config and node.config["parallel"] not in (True, False):
        errors.append(graph_node_rules._error("parallel_flag", f"{name}: parallel is on or off."))
    errors += _route_errors(node, graph, plan)
    return errors


def _route_errors(node: Any, graph: Any, plan: str) -> list[dict[str, str]]:
    name = graph_node_rules._name(node)
    exits = {edge.when: edge for edge in graph.exits(node.id)}
    errors = []
    if ROUTE_DONE not in exits:
        errors.append(graph_node_rules._error("parallel_routes", f"{name} needs an arrow for “{ROUTE_DONE}”."))
    replan = exits.get(ROUTE_REPLAN)
    if replan is None or replan.kind != graph_module.EDGE_LOOP or (plan and replan.target != plan):
        errors.append(graph_node_rules._error("parallel_routes", f"{name} needs a way back for “{ROUTE_REPLAN}” to the "
                                                             "step that plans the work.",
                                          edge_id=replan.id if replan is not None else None))
    return errors


__all__ = ["parallel_node_errors", "plan_node_id", "role_node", "roles_of", "runs_parallel"]
