"""The selected phase definition's governance wins over builder parameters, consumed fields never flow back, and no selection gets no definition fields."""

from __future__ import annotations

from app.services.workflow_contracts.selected_contract import (
    CONSUMED_DEFINITION_FIELDS,
    apply_selected_definition,
    build_selected_workflow_contract,
)
from tests.loop_contract_parity_support import _resolution

# --- precedence of apply_selected_definition -------------------------------------------------


def _built(**fields) -> dict:
    return {"workflow_id": "knowledge_request", "knowledge_query": "Report Builder", "requires_sources": True, **fields}


def test_definition_governance_wins_and_builder_parameters_are_kept():
    resolution = _resolution(
        "knowledge_request",
        "knowledge_request",
        allowed_tools=["knowledge_search"],
        requires_sources=False,
        knowledge_query="configured query",
        when_to_use="Use for documented facts.",
        empty_list=[],
    )

    contract = apply_selected_definition(_built(), resolution)

    assert contract["allowed_tools"] == ["knowledge_search"]  # carried through
    assert contract["requires_sources"] is False  # governed: the definition wins
    assert contract["knowledge_query"] == "Report Builder"  # builder-derived: kept
    assert contract["when_to_use"] == "Use for documented facts."
    assert "empty_list" not in contract
    assert contract["workflow_contract_source"] == "db_routing_policy"
    assert contract["workflow_routing_policy_matched_group_id"] is None
    # Idempotent: the loop seam re-applies it to the contract it receives.
    assert apply_selected_definition(contract, resolution) == contract


def test_consumed_fields_are_never_copied_back_from_the_definition():
    held = _resolution("knowledge_request", "knowledge_request", knowledge_query_style="summary")
    contract = build_selected_workflow_contract("What is Report Builder?", request_analysis={}, routing_resolution=held)

    # An unsupported style is refused by the builder, and stays refused on the merged contract.
    assert contract["knowledge_query_style"] == "lookup"
    assert contract["workflow_variant"]["state"] == "needs_configuration"
    assert "knowledge_query_style" in CONSUMED_DEFINITION_FIELDS["knowledge_request"]


def test_no_selection_and_non_db_selections_get_no_definition_fields():
    assert build_selected_workflow_contract("Create a presentation", request_analysis={}, routing_resolution=None) == {}
    built = _built()
    assert apply_selected_definition(built, {"source": "platform_workflow_service", "status": "selected"}) == built
    assert apply_selected_definition({}, _resolution("knowledge_request", "knowledge_request")) == {}
