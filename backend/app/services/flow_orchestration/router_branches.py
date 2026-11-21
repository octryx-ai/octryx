"""Branch selection of a router node, without an implicit first-connection fallback.

A router node picks a branch name (``route``): the first rule whose ``when`` matches, otherwise its
``default_route`` (``dag.node_execution._execute_router_node``). Its outgoing connections then decide
what runs next:

- a connection with a condition runs when that condition selects the branch. The condition is the
  branch name, ``route:<name>``, ``{"route": <name>}``, or a custom predicate over the router
  output;
- a connection without a condition (empty or falsy) is the explicit unconditional fallback. It
  runs when no conditional connection matched.

When neither exists, the router node fails with the closed configuration code
``router_branch_unmatched``, so a branch nobody connected never starts an agent or tool step. Nothing downstream runs;
the node, the run and the parent session get the same failed lifecycle as any other node failure. A
router without any connection is still a valid end of the flow.

The validator rejects only what can be proven statically: a declared branch (a reachable rule's
route or the default route) that no connection can select, on a router that has connections but
no unconditional fallback. A router with a custom predicate connection is never rejected, because
its coverage cannot be decided without the runtime output. The runtime guard covers it, and it also
checks every saved definition when the router runs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from ..runtime_failure_errors import ClassifiedFlowError
from .conditional_rules import ensure_connection_conditions_valid

ROUTER_BRANCH_UNMATCHED = "router_branch_unmatched"
ROUTER_BRANCH_UNCONNECTED = "router_branch_unconnected"
_ROUTE_PREFIX = "route:"


class RouterBranchUnmatchedError(ClassifiedFlowError):
    """The router picked a branch that no connection runs, and it has no unconditional fallback."""

    def __init__(self) -> None:
        super().__init__(
            ROUTER_BRANCH_UNMATCHED,
            category="input_contract_error",
            required_action="fix_workflow_configuration",
        )


def is_unconditional(condition: Any) -> bool:
    """A connection without a condition: the explicit fallback (same truthiness rule)."""
    return not condition


def select_router_targets(
    outgoing: list[dict[str, Any]], condition_matches: Callable[[Any], bool]
) -> set[str]:
    """The targets a router's chosen branch runs; raises :class:`RouterBranchUnmatchedError` instead of guessing.

    *outgoing* are the router's normalized edges (``target``, ``condition``); *condition_matches*
    evaluates one connection condition against the router output. A malformed custom predicate
    fails before any condition is evaluated.
    """
    ensure_connection_conditions_valid(edge.get("condition") for edge in outgoing)
    selected = {
        edge["target"]
        for edge in outgoing
        if not is_unconditional(edge.get("condition")) and condition_matches(edge.get("condition"))
    }
    if selected:
        return selected
    fallback = {edge["target"] for edge in outgoing if is_unconditional(edge.get("condition"))}
    if fallback or not outgoing:
        return fallback
    raise RouterBranchUnmatchedError()


def declared_router_branches(config: Any) -> list[str]:
    """Branch names a router can pick, in rule order, like ``_execute_router_node``.

    A rule without a ``when`` object always matches, so later rules and the default are unreachable.
    """
    config = config if isinstance(config, dict) else {}
    routes = config.get("routes") if isinstance(config.get("routes"), list) else []
    branches: list[str] = []
    for rule in routes:
        if not isinstance(rule, dict):
            continue
        branches.append(str(rule.get("route") or rule.get("target") or "default"))
        when = rule.get("when")
        if not (isinstance(when, dict) and when):
            return list(dict.fromkeys(branches))
    branches.append(str(config.get("default_route") or "default"))
    return list(dict.fromkeys(branches))


def _branches_selected_by(condition: Any) -> set[str] | None:
    """Branch names a connection condition selects; ``None`` for a custom predicate (undecidable)."""
    if isinstance(condition, str):
        return {condition, condition[len(_ROUTE_PREFIX):]} if condition.startswith(_ROUTE_PREFIX) else {condition}
    if isinstance(condition, dict):
        return {str(condition.get("route") or "")} if "route" in condition else None
    return set()  # Any other value never matches at runtime.


def unconnected_router_branches(config: Any, conditions: Iterable[Any]) -> list[str]:
    """Declared branches that provably have no connection; empty whenever that cannot be proven."""
    conditions = list(conditions)
    if not conditions or any(is_unconditional(condition) for condition in conditions):
        return []
    connected: set[str] = set()
    for condition in conditions:
        selected = _branches_selected_by(condition)
        if selected is None:
            return []
        connected.update(selected)
    return [branch for branch in declared_router_branches(config) if branch not in connected]


__all__ = [
    "ROUTER_BRANCH_UNCONNECTED",
    "ROUTER_BRANCH_UNMATCHED",
    "RouterBranchUnmatchedError",
    "declared_router_branches",
    "is_unconditional",
    "select_router_targets",
    "unconnected_router_branches",
]
