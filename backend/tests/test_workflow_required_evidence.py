"""A definition's required evidence tools gate its turn before the loop: an unavailable required tool is a
closed state before any tool runs; an optional connector never blocks."""



from app.services.workflow_contracts.registry import build_task_workflow_contract

_TOPOLOGY = {
    "workflow_id": "knowledge_request",
    "required_evidence_tools": ["aws_topology_snapshot"],
    "phases": [{"id": "draw", "preferred_tools": ["aws_topology_snapshot", "get_shape_library", "create_diagram"]}],
}










def test_the_built_contract_carries_the_definitions_required_tools():
    contract = build_task_workflow_contract(
        "What runs in our AWS account?",
        request_analysis={
            "workflow_contract": {
                "workflow_id": "knowledge_request",
                "required_evidence_tools": ["aws_topology_snapshot"],
            }
        },
    )
    assert contract["required_evidence_tools"] == ["aws_topology_snapshot"]


