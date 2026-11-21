from __future__ import annotations

from app.services.flow_node_registry import get_flow_node_contract, serialize_flow_node_registry


def test_flow_node_registry_serializes_required_contract_metadata() -> None:
    payload = serialize_flow_node_registry()
    items = {item["type"]: item for item in payload["items"]}

    assert payload["schema_version"] == "2.0"
    assert {
        "trigger",
        "output",
        "agent_step",
        "tool_step",
        "retrieval",
        "router",
        "parallel",
        "join",
        "approval",
        "evaluation",
        "learning_proposal",
        "error_handler",
        "subflow",
    } <= set(items)
    assert items["tool_step"]["calls_tools"] is True
    assert items["agent_step"]["calls_llm"] is True
    assert items["approval"]["can_pause"] is True
    assert items["output"]["can_end"] is True
    assert items["tool_step"]["required_config_any"] == ["tool", "allowed_tools"]


def test_flow_node_registry_lookup_returns_contract() -> None:
    contract = get_flow_node_contract("evaluation")

    assert contract is not None
    assert contract.type == "evaluation"
    assert contract.required_config_keys == ("quality_gate",)
