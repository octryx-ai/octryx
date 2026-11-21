"""Flow definition validation: node types, the explicit 2.0 schema version, configuration and edges, template metadata, field mappings and secrets."""

from __future__ import annotations

from app.services.flow_definitions import NOT_EXECUTABLE_NODE_TYPES, validate_flow_definition
from app.services.flow_node_registry import FLOW_NODE_REGISTRY
from tests.flow_definitions_support import _valid_flow_definition, _valid_v2_flow_definition


def _node(node_type: str) -> dict[str, object]:
    contract = FLOW_NODE_REGISTRY[node_type]
    config: dict[str, object] = {key: "x" for key in contract.required_config_keys}
    if contract.required_config_any:
        key = contract.required_config_any[0]
        config[key] = "knowledge_search" if key == "tool" else "x"
    return {"id": node_type, "type": node_type, "config": config}


def test_flow_validation_accepts_supported_node_types_and_empty_edges() -> None:
    executable = sorted(set(FLOW_NODE_REGISTRY) - set(NOT_EXECUTABLE_NODE_TYPES))
    report = validate_flow_definition(
        {"schema_version": "2.0", "nodes": [_node(node_type) for node_type in executable], "edges": []}
    )

    assert report["valid"] is True, report["errors"]
    assert report["node_types"] == executable


def test_flow_validation_refuses_node_types_a_flow_graph_cannot_run() -> None:
    """Review finding 12: an evaluation or subflow node fails at save/publish, not first at runtime."""
    for node_type in NOT_EXECUTABLE_NODE_TYPES:
        definition = _valid_flow_definition()
        definition["nodes"].append({"id": "late", "type": node_type, "config": {}})

        report = validate_flow_definition(definition)

        assert report["valid"] is False
        assert "node_type_not_executable" in {error["code"] for error in report["errors"]}


def test_flow_validation_refuses_a_definition_without_schema_version() -> None:
    definition = _valid_flow_definition()
    del definition["schema_version"]

    report = validate_flow_definition(definition)

    assert report["valid"] is False
    assert [error["code"] for error in report["errors"]] == ["missing_schema_version"]


def test_flow_validation_rejects_unsupported_schema_version() -> None:
    definition = _valid_flow_definition()
    definition["schema_version"] = "1.0"

    report = validate_flow_definition(definition)

    assert report["valid"] is False
    assert "unsupported_schema_version" in {error["code"] for error in report["errors"]}


def test_flow_validation_accepts_v2_definition() -> None:
    report = validate_flow_definition(_valid_v2_flow_definition())

    assert report["valid"] is True
    assert report["schema_version"] == "2.0"
    assert report["node_count"] == 3


def test_flow_validation_rejects_v2_missing_required_config() -> None:
    definition = _valid_v2_flow_definition()
    nodes = definition["nodes"]
    assert isinstance(nodes, list)
    retrieve = nodes[1]
    assert isinstance(retrieve, dict)
    retrieve["config"] = {}

    report = validate_flow_definition(definition)

    assert report["valid"] is False
    assert "missing_required_config" in {error["code"] for error in report["errors"]}


def test_flow_validation_rejects_v2_invalid_field_edge() -> None:
    definition = _valid_v2_flow_definition()
    edges = definition["edges"]
    assert isinstance(edges, list)
    edges[1] = {
        "source_node_id": "retrieve",
        "source_field": "missing",
        "target_node_id": "answer",
        "target_field": "evidence",
    }

    report = validate_flow_definition(definition)

    assert report["valid"] is False
    assert "unknown_source_field" in {error["code"] for error in report["errors"]}


def test_flow_validation_accepts_template_metadata_for_builder_drafts() -> None:
    definition = _valid_flow_definition()
    definition["template_metadata"] = {
        "template_key": "person-source-evidence-research",
        "evidence_contract": {"required_sources": ["jira", "confluence", "bitbucket"]},
        "sample_test_case": {"input": "Who is Alice Example?", "expected": "Evidence-backed profile"},
        "quality_gate_binding": {"gate": "source_evidence_required"},
    }

    report = validate_flow_definition(definition)

    assert report["valid"] is True


def test_flow_validation_rejects_schema_contract_mismatch() -> None:
    report = validate_flow_definition(
        {
            "schema_version": "2.0",
            "nodes": [
                {"id": "source", "type": "trigger", "output_schema": {"available": "string"}},
                {"id": "target", "type": "agent_step", "input_schema": {"missing": "string"},
                 "config": {"prompt": "Answer."}},
            ],
            "edges": [{"source_node_id": "source", "target_node_id": "target"}],
        }
    )

    assert report["valid"] is False
    assert {error["code"] for error in report["errors"]} == {"schema_contract_mismatch"}


def test_flow_validation_accepts_edge_field_mapping_aliases() -> None:
    report = validate_flow_definition(
        {
            "schema_version": "2.0",
            "nodes": [
                {"id": "source", "type": "trigger", "output_schema": {"request": "string"}},
                {"id": "target", "type": "tool_step", "input_schema": {"arguments": "object"},
                 "config": {"tool": "knowledge_search"}},
            ],
            "edges": [
                {
                    "source_node_id": "source",
                    "target_node_id": "target",
                    "source_field": "request",
                    "target_field": "arguments",
                }
            ],
        }
    )

    assert report["valid"] is True


def test_flow_validation_rejects_raw_secret_values_and_accepts_secret_refs() -> None:
    raw_report = validate_flow_definition(
        {
            "schema_version": "2.0",
            "nodes": [{"id": "tool", "type": "tool_step", "config": {"tool": "knowledge_search", "api_key": "plain-secret"}}],
            "edges": [],
        }
    )
    ref_report = validate_flow_definition(
        {
            "schema_version": "2.0",
            "nodes": [{"id": "tool", "type": "tool_step",
                       "config": {"tool": "knowledge_search", "api_key": "secret://github/token"}}],
            "edges": [],
        }
    )

    assert raw_report["valid"] is False
    assert {error["code"] for error in raw_report["errors"]} == {"raw_secret_value"}
    assert ref_report["valid"] is True
