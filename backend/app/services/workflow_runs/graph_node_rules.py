"""The closed validation of a phased graph's nodes: each kind's own rules, a phase's contract and path rules."""

from __future__ import annotations

from typing import Any

from .graph import (
    CONFIRMATION_SUBJECTS,
    GATE_CHECK_TYPES,
    NODE_CONFIRMATION,
    NODE_CONVERSATION,
    NODE_DECISION,
    NODE_GATE,
    NODE_OUTCOME,
    NODE_PARALLEL,
    NODE_PHASE,
    NODE_PLATFORM_ACTION,
    NODE_REVIEW,
    NODE_SUB_WORKFLOW,
    NODE_WATCH,
    WATCH_CONDITIONS,
    PhasedGraph,
    PhasedNode,
    _text,
    route_values,
)
from .states import OUTCOMES


def _error(code: str, message: str, *, node_id: str | None = None, edge_id: str | None = None) -> dict[str, str]:
    error = {"code": code, "message": message}
    if node_id:
        error["node_id"] = node_id
    if edge_id:
        error["edge_id"] = edge_id
    return error


def _name(node: PhasedNode) -> str:
    return f"“{node.title or node.id}”"


def _validate_phase(node: PhasedNode) -> list[dict[str, str]]:
    from .phase_validation import validate_phase_payload
    from .records import has_done_criteria

    contract = node.config.get("workflow_contract")
    if not isinstance(contract, dict):
        return [_error("phase_without_contract", f"{_name(node)}: say what this step may do and when it is done.",
                       node_id=node.id)]
    payload = {
        "workflow_id": node.config.get("workflow_id") or contract.get("workflow_id"),
        "workflow_class": node.config.get("workflow_class") or contract.get("workflow_class"),
        "workflow_contract": contract, "tool_policy": node.config.get("tool_policy") or {},
        "safety_constraints": node.config.get("safety_constraints") or {},
    }
    errors = [
        _error(item["code"], f"{_name(node)}: {item['message']}", node_id=node.id)
        for item in validate_phase_payload(payload)["errors"]
    ]
    if _text(contract.get("capability_class")) not in {"read_only", "change", "deliver"}:
        errors.append(_error("phase_capability_class", f"{_name(node)}: choose what this step may do.",
                             node_id=node.id))
    if not has_done_criteria(contract):
        errors.append(_error("phase_without_checks", f"{_name(node)} needs a step or a “done when” check, so the run "
                                                     "knows when it is done.", node_id=node.id))
    rules = contract.get("path_rules")
    if rules is not None:
        errors += _path_rule_errors(node, rules)
    from .octryx.seat_models import NODE_CLASS_KEY, classes

    model_class = node.config.get(NODE_CLASS_KEY)
    if model_class is not None and model_class not in classes():
        errors.append(_error("phase_model_class", f"{_name(node)}: the model class is one of {', '.join(classes())}.",
                             node_id=node.id))
    from .conditions import result_values_errors
    from .slices.rules import validate_sub_agents

    errors += result_values_errors(node)
    sub_agent_errors = validate_sub_agents(node.id, node.config.get("sub_agents"))
    return errors + [{**item, "node_id": node.id} for item in sub_agent_errors]


def _path_rule_errors(node: PhasedNode, rules: Any) -> list[dict[str, str]]:
    from .path_rules import PATH_UNCHECKED_TOOLS, PROTECT_CONFIRMED_TESTS

    if not isinstance(rules, dict) or not rules or set(rules) - {"write", "create", PROTECT_CONFIRMED_TESTS}:
        return [_error("invalid_path_rules", f"{_name(node)}: the rules for writing files take write, create "
                                             f"and/or {PROTECT_CONFIRMED_TESTS}.", node_id=node.id)]
    for key in ("write", "create"):
        patterns = rules.get(key)
        if patterns is not None and (not isinstance(patterns, list) or not patterns
                                     or not all(_text(item) for item in patterns)):
            return [_error("invalid_path_rules", f"{_name(node)}: list at least one folder pattern under {key}.",
                           node_id=node.id)]
    if rules.get("create") is not None and rules.get(PROTECT_CONFIRMED_TESTS) is not True:
        return [_error("invalid_path_rules", f"{_name(node)}: new files can only be allowed when the confirmed "
                                             f"tests are protected ({PROTECT_CONFIRMED_TESTS}).", node_id=node.id)]
    if PROTECT_CONFIRMED_TESTS in rules and rules[PROTECT_CONFIRMED_TESTS] not in (True, False):
        return [_error("invalid_path_rules", f"{_name(node)}: {PROTECT_CONFIRMED_TESTS} is on or off.",
                       node_id=node.id)]
    policy = node.config.get("tool_policy") if isinstance(node.config.get("tool_policy"), dict) else {}
    shells = sorted(PATH_UNCHECKED_TOOLS & {_text(item) for item in policy.get("allowlist") or []})
    if shells:
        return [_error("path_rules_with_shell", f"{_name(node)} has rules for writing files, so it cannot use "
                                                f"{', '.join(shells)}: a shell could write anywhere.",
                       node_id=node.id)]
    return []


def _validate_node(node: PhasedNode, graph: PhasedGraph) -> list[dict[str, str]]:
    return [item if item.get("node_id") else {**item, "node_id": node.id} for item in _node_errors(node, graph)]


def _node_errors(node: PhasedNode, graph: PhasedGraph) -> list[dict[str, str]]:
    config = node.config
    name = _name(node)
    if node.kind == NODE_REVIEW:
        from .review.artefact_contract import config_errors

        return config_errors(node, graph)
    if node.kind == NODE_PHASE:
        return _validate_phase(node)
    if node.kind == NODE_PARALLEL:
        from .teamwork.node import parallel_node_errors

        return parallel_node_errors(node, graph)
    if node.kind == NODE_GATE:
        return _gate_errors(node, graph, name)
    if node.kind == NODE_DECISION:
        from .conditions import decision_errors

        return decision_errors(node, graph)
    if node.kind == NODE_OUTCOME and _text(config.get("outcome")) not in OUTCOMES:
        return [_error("outcome_value", f"{name}: choose how the workflow ends ({', '.join(sorted(OUTCOMES))}).")]
    if node.kind == NODE_OUTCOME:
        from .triage_routing import routing_errors

        return routing_errors(node)
    if node.kind == NODE_PLATFORM_ACTION and _text(config.get("action")):
        from .platform.catalog import validate_action_config

        return validate_action_config(node.id, config)
    if node.kind == NODE_PLATFORM_ACTION:
        if not _text(config.get("tool")):
            return [_error("action_without_tool", f"{name}: choose what the platform does.")]
        if "arguments" in config and not isinstance(config.get("arguments"), dict):
            return [_error("action_arguments", f"{name}: the arguments must be a set of named values.")]
    if node.kind == NODE_CONFIRMATION and _text(config.get("subject")) not in CONFIRMATION_SUBJECTS:
        return [_error("confirmation_subject", f"{name}: choose what the person confirms.")]
    if node.kind == NODE_CONVERSATION and not _text(config.get("question")):
        return [_error("conversation_question", f"{name}: write the question the person is asked.")]
    if node.kind == NODE_WATCH:
        conditions = route_values(node) or frozenset()
        if not conditions or not conditions <= WATCH_CONDITIONS:
            return [_error("watch_conditions", f"{name}: choose at least one known event to wait for.")]
        from .watch_rules import validate_watch

        return validate_watch(node, graph)
    if node.kind == NODE_SUB_WORKFLOW:
        return _sub_workflow_errors(config, name)
    return []


def _gate_errors(node: PhasedNode, graph: PhasedGraph, name: str) -> list[dict[str, str]]:
    from ..workflow_checks.library import validate_checks

    config = node.config
    checks = config.get("checks")
    if not isinstance(checks, list) or not checks:
        return [_error("gate_without_checks", f"{name} needs at least one check.")]
    errors = [_error(item["code"], f"{name}: {item['message']}") for item in validate_checks(checks)]
    for check in checks:
        if isinstance(check, dict) and _text(check.get("type")) not in GATE_CHECK_TYPES:
            message = f"{name} cannot judge a “{check.get('type')}” check."
            errors.append(_error("gate_check_type", message))
    phase = _text(config.get("phase"))
    if phase and (phase not in graph.nodes or graph.nodes[phase].kind != NODE_PHASE):
        errors.append(_error("gate_phase", f"{name} looks at an agent step that does not exist ({phase})."))
    return errors


def _sub_workflow_errors(config: dict[str, Any], name: str) -> list[dict[str, str]]:
    if not _text(config.get("workflow_key")):
        return [_error("sub_workflow_key", f"{name}: choose the workflow that runs here.")]
    if "child_version_id" in config or "child_checksum" in config:
        # An exact pinned child (id + canonical checksum) only for a typed handoff/v1 offer.
        version, checksum = config.get("child_version_id"), config.get("child_checksum")
        if (not isinstance(config.get("handoff"), dict) or not isinstance(version, str) or not version.strip()
                or not isinstance(checksum, str) or len(checksum) != 71 or not checksum.startswith("sha256:")):
            return [_error("invalid_child_pin", f"{name} pins a child by version id and sha256 checksum, with a "
                                                "handoff/v1 contract.")]
    if "handoff" in config:
        if isinstance(config["handoff"], dict):
            from fastapi import HTTPException

            from .handoff.contract import validate_contract

            try:
                validate_contract(config["handoff"])
            except HTTPException:
                return [_error("invalid_handoff", f"{name} needs a valid handoff/v1 contract.")]
        elif not isinstance(config["handoff"], list):
            return [_error("invalid_handoff", f"{name}: the handoff must be a list or handoff/v1.")]
    return []
