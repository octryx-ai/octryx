"""Valid flow definitions and payloads shared by the flow definition tests."""

from __future__ import annotations


def _valid_flow_definition() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "nodes": [
            {
                "id": "ticket-trigger",
                "type": "trigger",
                "output_schema": {"request": "object"},
            },
            {
                "id": "normalize-input",
                "type": "input_schema",
                "input_schema": {"request": "object"},
                "output_schema": {"intent": "string"},
            },
            {
                "id": "retrieve-context",
                "type": "retrieval",
                "input_schema": {"intent": "string"},
                "output_schema": {"evidence": "array"},
            },
            {
                "id": "coding-agent",
                "type": "agent_step",
                "input_schema": {"evidence": "array"},
                "output_schema": {"draft": "string"},
                "config": {"prompt": "Draft the change from the evidence."},
            },
            {
                "id": "human-approval",
                "type": "approval",
                "input_schema": {"draft": "string"},
                "output_schema": {"approved": "boolean", "draft": "string"},
            },
            {
                "id": "final-output",
                "type": "output",
                "input_schema": {"approved": "boolean"},
            },
        ],
        "edges": [
            {"source_node_id": "ticket-trigger", "target_node_id": "normalize-input"},
            {"source_node_id": "normalize-input", "target_node_id": "retrieve-context"},
            {"source_node_id": "retrieve-context", "target_node_id": "coding-agent"},
            {"source_node_id": "coding-agent", "target_node_id": "human-approval"},
            {"source_node_id": "human-approval", "target_node_id": "final-output"},
        ],
    }


def _valid_v2_flow_definition() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "metadata": {
            "name": "V2 Evidence Flow",
            "workflow_class": "knowledge",
            "runtime_mode": "controlled",
            "tags": ["test"],
        },
        "nodes": [
            {
                "id": "input",
                "type": "trigger",
                "label": "Input",
                "output_schema": {"request": "string"},
                "config": {"trigger_type": "manual"},
            },
            {
                "id": "retrieve",
                "type": "tool_step",
                "label": "Retrieve evidence",
                "input_schema": {"request": "string"},
                "output_schema": {"evidence": "array"},
                "config": {"tool": "knowledge_search"},
                "retry_policy": {"max_attempts": 2},
                "timeout_policy": {"seconds": 30},
                "budget_hints": {"max_tool_calls": 1},
            },
            {
                "id": "answer",
                "type": "output",
                "label": "Answer",
                "input_schema": {"evidence": "array"},
            },
        ],
        "edges": [
            {"source_node_id": "input", "target_node_id": "retrieve"},
            {"source_node_id": "retrieve", "target_node_id": "answer"},
        ],
        "io_mappings": [
            {"source": "$input.request", "target": "input.request"},
            {"source": "retrieve.evidence", "target": "$output.evidence"},
        ],
        "runtime_settings": {"max_parallel_nodes": 2},
        "publish_settings": {"expose_as_capability": False},
    }


def _flow_payload(project_id: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "key": "coding-delivery-standard-flow",
        "name": "Coding Delivery Standard Flow",
        "description": "Versioned flow definition for coding-agent delivery orchestration.",
        "definition": _valid_flow_definition(),
        "runtime_settings": {"max_parallel_nodes": 3},
        "policy_bindings": {"approval_policy": "admin-required"},
    }
