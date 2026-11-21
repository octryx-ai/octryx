"""Validation of a flow definition: phased graphs and fragments by their own validators, DAG flow graphs by the
schema 2.0 contract (an explicit ``schema_version`` is required)."""

from __future__ import annotations

from typing import Any

from ..flow_v2_validation import validate_flow_definition_v2
from ..run_capability.flow_capability import validate_flow_capability_class

# A DAG flow graph states its schema explicitly; only the 2.0 contract exists.
FLOW_SCHEMA_VERSION = "2.0"


# Node types a flow graph cannot run (the DAG executor refuses them): refused when a version is saved or published.
NOT_EXECUTABLE_NODE_TYPES = {"evaluation": "a gate", "subflow": "a sub_workflow node"}


def _not_executable_node_errors(definition: dict[str, Any]) -> list[dict[str, str]]:
    nodes = definition.get("nodes") if isinstance(definition.get("nodes"), list) else []
    return [
        {"code": "node_type_not_executable",
         "message": f"Node {node.get('id')}: a '{node.get('type')}' node does not run in a flow graph; use "
                    f"{NOT_EXECUTABLE_NODE_TYPES[str(node.get('type'))]} in a workflow that runs in phases."}
        for node in nodes
        if isinstance(node, dict) and str(node.get("type") or "") in NOT_EXECUTABLE_NODE_TYPES
    ]


def validate_flow_definition(definition: dict[str, Any]) -> dict[str, Any]:
    from ..workflow_runs.fragments.store import is_fragment
    from ..workflow_runs.graph import is_phased_definition
    from ..workflow_runs.graph_validation import validate_phased_definition

    if is_fragment(definition):
        # A fragment is validated inside its harness graph by the same phased validator.
        from ..workflow_runs.fragments.validation import validate_fragment_definition

        return validate_fragment_definition(definition)
    if is_phased_definition(definition):
        # "Runs in phases" has its own closed graph (bounded loop edges, outcomes), not the DAG contract.
        return validate_phased_definition(definition)
    errors: list[dict[str, str]] = []
    schema_version = str(definition.get("schema_version") or "").strip()
    if schema_version != FLOW_SCHEMA_VERSION:
        return {
            "valid": False,
            "errors": [_schema_version_error(schema_version)],
            "warnings": [],
            "schema_version": schema_version or None,
        }
    # The class the flow's tool nodes dispatch under: validated like a workflow definition's.
    errors.extend(validate_flow_capability_class(definition))
    errors.extend(_not_executable_node_errors(definition))
    report = validate_flow_definition_v2(definition)
    if errors:
        report["valid"] = False
        report["errors"] = errors + list(report.get("errors") or [])
    return report


def _schema_version_error(schema_version: str) -> dict[str, str]:
    if not schema_version:
        return {"code": "missing_schema_version",
                "message": f"A flow definition states its schema_version ({FLOW_SCHEMA_VERSION})."}
    return {"code": "unsupported_schema_version",
            "message": f"Unsupported Flow Definition schema_version: {schema_version} (only {FLOW_SCHEMA_VERSION})."}
