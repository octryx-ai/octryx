"""A workflow-run phase resolution builds the family contract with the phase definition's governance and provenance."""

from app.services.workflow_contracts.selected_contract import build_selected_workflow_contract


def test_a_knowledge_phase_resolution_builds_the_knowledge_contract():
    prompt = "what can you tell me about Report Builder?"
    resolution = {
        "source": "db",
        "status": "matched",
        "selection_source": "workflow_run",
        "workflow_key": "knowledge-phase",
        "workflow_id": "knowledge_request",
        "workflow_class": "knowledge_request",
        "policy_id": "policy-3",
        "policy_version_id": "version-3",
        "matched_group_id": None,
        "workflow_contract": {
            "workflow_id": "knowledge_request",
            "workflow_class": "knowledge_request",
            "requires_sources": True,
        },
    }

    resolved = build_selected_workflow_contract(prompt, request_analysis={}, routing_resolution=resolution)

    assert resolved["workflow_id"] == "knowledge_request"
    assert resolved["knowledge_query"] == "Report Builder"
    assert resolved["workflow_class"] == "knowledge_request"
    assert resolved["workflow_contract_source"] == "db_routing_policy"
    assert resolved["workflow_routing_policy_id"] == "policy-3"
    assert resolved["workflow_routing_policy_version_id"] == "version-3"
    assert resolved["workflow_routing_policy_matched_group_id"] is None
    assert resolved["requires_sources"] is True
    assert resolved["source_user_message"] == prompt


def test_a_resolution_that_selects_no_workflow_builds_no_contract():
    resolution = {"source": "db", "status": "matched", "selection_source": "explicit_workflow_key",
                  "workflow_id": "knowledge_request", "workflow_contract": {"workflow_id": "knowledge_request"}}

    # Only a workflow-run phase selects a workflow from a db resolution.
    assert build_selected_workflow_contract(
        "what can you tell me about Report Builder?", request_analysis={}, routing_resolution=resolution
    ) == {}
