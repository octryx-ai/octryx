"""The data-flow law of a phased workflow: every consumed artefact has a producer before it."""

from __future__ import annotations

from typing import Any

from .graph import (
    NODE_CONFIRMATION,
    NODE_GATE,
    NODE_PHASE,
    NODE_PLATFORM_ACTION,
    NODE_REVIEW,
    NODE_START,
    NODE_SUB_WORKFLOW,
    PhasedGraph,
    PhasedNode,
)
from .graph_validation import _ancestors

CHANGE_PLAN = "change_plan"
REVIEW_VERDICT = "review_verdict"
CONFIRMED_TESTS = "confirmed_tests"
DRAFT_CHANGE_PLAN = "work.draft_change_plan"
CREATE_STORIES = "work.create_stories"
SUBJECT_REQUIRES = {"test_contract": CHANGE_PLAN, "reproduction": "reproduction", "questions": "definition_of_ready"}
TEXT_SOURCE_REQUIRES = {"dor_questions": "definition_of_ready", "review": REVIEW_VERDICT,
                        "hypothesis": "incident_hypothesis"}
# The TDD checks judge the confirmed tests when there are any, else the tests they name or the whole suite.
CHECK_REQUIRES = {"definition_of_ready": "definition_of_ready", "review_passed": REVIEW_VERDICT,
                  "artefact_review_passed": "artefact_review_verdict"}
_TEXT_PARAMS = ("text_from", "summary_from", "description_from")
# What a run may receive only through an accepted typed handoff (``handoff.specification``).
HANDOFF_INPUT_KINDS = frozenset({"spec"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _submit_checked(node: PhasedNode, tool: str) -> bool:
    policy = node.config.get("tool_policy") if isinstance(node.config.get("tool_policy"), dict) else {}
    contract = node.config.get("workflow_contract") if isinstance(node.config.get("workflow_contract"), dict) else {}
    offered = tool in (policy.get("allowlist") or []) and tool not in (policy.get("denylist") or [])
    return offered and any(
        isinstance(check, dict) and check.get("type") == "tool_called" and check.get("blocking") is not False
        and tool in (dict(check.get("params") or {}).get("tools") or []) for check in contract.get("checks") or [])


def handoff_inputs(node: PhasedNode | None) -> set[str]:
    raw = node.config.get("handoff_inputs") if node is not None and node.kind == NODE_START else None
    if not isinstance(raw, list):
        return set()
    return {item for item in raw if isinstance(item, str) and item in HANDOFF_INPUT_KINDS}


def receives_spec(graph: PhasedGraph) -> bool:
    return "spec" in handoff_inputs(graph.start())


def produces(node: PhasedNode) -> set[str]:
    from .phase_outputs import OUTPUT_SPECS, phase_output

    if node.kind == NODE_START:
        return handoff_inputs(node)
    if node.kind == NODE_PHASE:
        # Declared (``output``), or — a version before output contracts — a submit tool the phase must call.
        return ({phase_output(node)} - {""}) | {spec.kind for spec in OUTPUT_SPECS.values()
                                                 if _submit_checked(node, spec.tool)}
    if node.kind == NODE_PLATFORM_ACTION and _text(node.config.get("action")) == DRAFT_CHANGE_PLAN:
        return {CHANGE_PLAN}
    if node.kind == NODE_REVIEW:
        return {"artefact_review_verdict"} if node.config.get("mode") == "artefact" else {REVIEW_VERDICT}
    if node.kind == NODE_CONFIRMATION and _text(node.config.get("subject")) in ("test_contract", "reproduction"):
        return {CONFIRMED_TESTS}
    from .documentation.flow import documentation_produces

    return documentation_produces(node.kind, node.config)


def consumes(node: PhasedNode) -> set[str]:
    from .phase_outputs import phase_inputs

    config = node.config
    needed: set[str] = set()
    if node.kind == NODE_CONFIRMATION:
        subject = _text(config.get("subject"))
        needed |= {SUBJECT_REQUIRES[subject]} if subject in SUBJECT_REQUIRES else set()
        needed |= {_text(config.get("shows"))} - {""}
    if node.kind == NODE_PLATFORM_ACTION:
        if _text(config.get("action")) == DRAFT_CHANGE_PLAN:
            needed.add("test_contract")
        if _text(config.get("action")) == CREATE_STORIES:
            needed.add("story_plan")
        params = config.get("params") if isinstance(config.get("params"), dict) else {}
        needed |= {TEXT_SOURCE_REQUIRES[_text(params.get(name))] for name in _TEXT_PARAMS
                   if _text(params.get(name)) in TEXT_SOURCE_REQUIRES}
    if node.kind == NODE_PHASE:
        needed |= set(phase_inputs(node))
    if node.kind == NODE_SUB_WORKFLOW and isinstance(config.get("handoff"), list):
        needed |= {_text(item) for item in config["handoff"] if _text(item)}
    if node.kind == NODE_GATE:
        needed |= {CHECK_REQUIRES[_text(check.get("type"))] for check in config.get("checks") or []
                   if isinstance(check, dict) and _text(check.get("type")) in CHECK_REQUIRES}
        needed |= {_text(dict(check.get("params") or {}).get("kind"))
                   for check in config.get("checks") or [] if isinstance(check, dict)
                   and check.get("type") == "specification_ready"} - {""}
    from .documentation.flow import documentation_consumes

    return needed | documentation_consumes(node.kind, config)


def missing_producers(graph: PhasedGraph, node: PhasedNode) -> list[str]:
    available: set[str] = set()
    for ancestor in _ancestors(graph, node.id):
        if ancestor in graph.nodes:
            available |= produces(graph.nodes[ancestor])
    return sorted(consumes(node) - available)


def _output_errors(node: PhasedNode) -> list[dict[str, str]]:
    from .phase_outputs import OUTPUT_SPECS, phase_inputs, phase_output

    errors: list[dict[str, str]] = []
    kind = phase_output(node)
    unknown = [item for item in ([kind] if kind else []) + phase_inputs(node) if item not in OUTPUT_SPECS]
    if unknown:
        return [{"code": "unknown_phase_output", "message": f"Phase '{node.id}' names an unknown output: "
                 f"{', '.join(unknown)} (one of {', '.join(sorted(OUTPUT_SPECS))})."}]
    if not kind:
        return []
    tool = OUTPUT_SPECS[kind].tool
    if not _submit_checked(node, tool):
        errors.append({"code": "phase_output_contract", "message": f"Phase '{node.id}' submits a {kind}, so it "
                       f"offers {tool} and a blocking tool_called check names it."})
    return errors


def _handoff_input_errors(graph: PhasedGraph) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for node in graph.nodes.values():
        if "handoff_inputs" in node.config:
            raw = node.config["handoff_inputs"]
            if (node.kind != NODE_START or not isinstance(raw, list) or not raw
                    or len(set(map(str, raw))) != len(raw) or handoff_inputs(node) != set(raw)):
                errors.append({"code": "handoff_inputs_invalid", "message": (
                    f"Node '{node.id}': handoff_inputs is a start node's distinct list of "
                    f"{', '.join(sorted(HANDOFF_INPUT_KINDS))}.")})
        if node.config.get("decider") == "spec_origin" and not receives_spec(graph):
            errors.append({"code": "spec_origin_without_handoff", "message": (
                f"Node '{node.id}' decides by spec_origin, but the workflow receives no accepted spec "
                "(its start declares handoff_inputs: [spec]).")})
    return errors


def data_flow_errors(graph: PhasedGraph) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = _handoff_input_errors(graph)
    for node in graph.ordered_nodes():
        if node.kind == NODE_PHASE:
            errors += _output_errors(node)
        if node.kind == NODE_CONFIRMATION and _text(node.config.get("subject")) == "ticket_draft":
            before = {item for item in _ancestors(graph, node.id) if graph.nodes.get(item, node).kind == NODE_PHASE}
            source = _text(node.config.get("payload_from"))
            if not before or (source and source not in before):
                errors.append({"code": "confirmation_without_producer", "message": f"Confirmation '{node.id}' shows "
                               "a drafted ticket: a phase before it drafts it (payload_from names it, else the last "
                               "phase)."})
        missing = missing_producers(graph, node)
        if missing:
            errors.append({"code": "consumer_without_producer", "message": (
                f"Node '{node.id}' needs {', '.join(missing)}, but no step before it produces "
                f"{'it' if len(missing) == 1 else 'them'} (a phase with that output, work.draft_change_plan, a "
                "review or a test confirmation).")})
    return errors


__all__ = ["CHANGE_PLAN", "DRAFT_CHANGE_PLAN", "HANDOFF_INPUT_KINDS", "REVIEW_VERDICT", "consumes",
           "data_flow_errors", "handoff_inputs", "missing_producers", "produces", "receives_spec"]
