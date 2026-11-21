"""The session tool catalog records the routing resolution's tool policy metadata and the tool plan contract records its effect."""

from app.services.tool_catalog import build_session_tool_catalog
from app.services.tool_planning import build_trace_only_tool_plan_contract
from tests.tool_plan_contract_support import _definition


def test_session_tool_catalog_records_db_routing_policy_metadata():
    catalog = build_session_tool_catalog(
        tool_definitions=[_definition("aws_topology_snapshot"), _definition("get_shape_library")],
        capability_type="admin",
        request_analysis={
            "workflow_routing_policy_resolution": {
                "source": "db",
                "status": "matched",
                "policy_id": "policy-1",
                "policy_version_id": "version-1",
                "matched_group_id": "aws-topology-diagram-message",
                "tool_policy": {
                    "allowlist": ["aws_topology_snapshot", "get_shape_library", "create_diagram"],
                    "denylist": ["bash"],
                },
            }
        },
        workflow_contract={"workflow_id": "generic_diagram"},
    )

    assert catalog["policy_source"] == "workflow_routing_policy"
    assert catalog["routing_policy_id"] == "policy-1"
    assert catalog["routing_policy_matched_group_id"] == "aws-topology-diagram-message"
    assert catalog["policy_allowlist_count"] == 3
    assert catalog["policy_denylist_count"] == 1


def test_tool_plan_contract_records_policy_effect_in_intent_contract():
    catalog = build_session_tool_catalog(
        tool_definitions=[_definition("knowledge_search")],
        capability_type="diagnosis",
        request_analysis={
            "requested_domains": ["knowledge"],
            "workflow_routing_policy_resolution": {
                "source": "db",
                "status": "matched",
                "policy_id": "policy-knowledge",
                "policy_version_id": "version-knowledge",
                "matched_group_id": "knowledge-query",
                "tool_policy": {
                    "allowlist": ["knowledge_search", "knowledge_read", "search_confluence"],
                    "denylist": ["search_confluence"],
                },
            },
        },
        workflow_contract=None,
    )

    plan = build_trace_only_tool_plan_contract(
        current_turn_content="What do we know about Report Builder?",
        request_analysis={"requested_domains": ["knowledge"], "evidence_axes": ["source"]},  # never read
        workflow_contract={"workflow_id": "knowledge_request"},
        session_tool_catalog=catalog,
    )

    intent = plan["intent_contract"]
    assert intent["catalog_policy_source"] == "workflow_routing_policy"
    assert intent["requested_domains"] == ["knowledge"]
    assert "evidence_axes" not in intent
    assert intent["selected_tool_count"] == 1
    assert intent["denied_tool_count"] == 1
    assert intent["skipped_policy_tool_count"] == 1
    assert intent["unavailable_policy_tool_count"] == 1
    assert intent["fallback_policy"] == "workflow_process_toolset"
