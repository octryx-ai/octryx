from app.services.tool_catalog import build_session_tool_catalog, resolve_session_tool_catalog
from app.tools.context import ToolContext
from app.tools.definitions import get_all_definitions


def _definition(name: str) -> dict:
    return get_all_definitions()[name]


def test_session_tool_catalog_summarizes_resolved_tools():
    catalog = build_session_tool_catalog(
        tool_definitions=[
            _definition("aws_topology_snapshot"),
            _definition("get_shape_library"),
            _definition("create_diagram"),
        ],
        capability_type="admin",
        request_analysis={"route_reason": "contextual_request", "requested_domains": ["aws"]},
        workflow_contract={"workflow_id": "generic_diagram"},
    )

    assert catalog["mode"] == "trace_only"
    assert catalog["tool_count"] == 3
    assert catalog["availability_reason"] == "workflow:generic_diagram"
    assert catalog["category_counts"]["cloud/aws"] == 1
    assert catalog["category_counts"]["diagram"] == 2
    assert {entry["name"] for entry in catalog["entries"]} == {
        "aws_topology_snapshot",
        "create_diagram",
        "get_shape_library",
    }


def test_session_tool_catalog_marks_approval_hints_as_high_risk():
    catalog = build_session_tool_catalog(
        tool_definitions=[_definition("aws_action_operation")],
        capability_type="admin",
        request_analysis={"route_reason": "operations_keywords"},
        workflow_contract=None,
    )

    entry = catalog["entries"][0]
    assert entry["name"] == "aws_action_operation"
    assert entry["approval_hint"] is True
    assert entry["risk_level"] == "high"
    assert catalog["approval_hint_count"] == 1
    assert catalog["risk_counts"]["high"] == 1


def test_session_tool_catalog_is_empty_for_empty_resolved_catalog():
    catalog = build_session_tool_catalog(
        tool_definitions=[],
        capability_type="diagnosis",
        request_analysis={"route_reason": "default_standard"},
        workflow_contract=None,
    )

    assert catalog["tool_count"] == 0
    assert catalog["entries"] == []
    assert catalog["category_counts"] == {}
    assert catalog["availability_reason"] == "request_analysis:default_standard"


def test_session_tool_catalog_records_session_scope_without_secrets():
    catalog = build_session_tool_catalog(
        tool_definitions=[_definition("knowledge_search")],
        capability_type="diagnosis",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=["customer", "support"],
            roles=["member", "knowledge-admin"],
            session_id="session-1",
            project_config={"secrets": {"should_not": "appear"}},
            db=None,
            workspace_root="/tmp/workspace",
        ),
    )

    scope = catalog["session_scope"]
    assert scope == {
        "scope_source": "tool_context",
        "session_id": "session-1",
        "user_id": "user-1",
        "project_ids": ["customer", "support"],
        "omitted_project_id_count": 0,
        "roles": ["member", "knowledge-admin"],
        "omitted_role_count": 0,
    }
    assert "project_config" not in scope
    assert "secrets" not in str(catalog)


def test_session_tool_catalog_records_policy_effects():
    catalog = build_session_tool_catalog(
        tool_definitions=[_definition("aws_topology_snapshot"), _definition("get_shape_library")],
        capability_type="diagnosis",
        request_analysis={
            "workflow_routing_policy_resolution": {
                "source": "db",
                "status": "matched",
                "policy_id": "policy-1",
                "policy_version_id": "version-1",
                "matched_group_id": "aws-topology",
                "tool_policy": {
                    "allowlist": ["aws_topology_snapshot", "get_shape_library", "create_diagram", "bash"],
                    "denylist": ["bash"],
                },
            }
        },
        workflow_contract={"workflow_id": "generic_diagram"},
    )

    assert catalog["contract_kind"] == "session_aware_tool_catalog"
    assert catalog["contract_version"] == 2
    assert catalog["policy_allowlist_count"] == 4
    assert catalog["policy_denylist_count"] == 1
    assert catalog["denied_tools"] == ["bash"]
    assert catalog["skipped_policy_tools"] == ["bash"]
    assert catalog["unavailable_policy_tools"] == ["create_diagram"]


def test_session_tool_catalog_resolver_wraps_catalog_with_lifecycle():
    resolution = resolve_session_tool_catalog(
        tool_definitions=[_definition("knowledge_search")],
        capability_type="diagnosis",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=None,
        tool_context=ToolContext(
            user_id="user-1",
            project_ids=["customer"],
            roles=["member"],
            session_id="session-1",
            project_config={},
            db=None,
            workspace_root="/tmp/workspace",
        ),
    )

    assert resolution["contract_kind"] == "session_tool_catalog_resolution"
    assert resolution["status"] == "resolved"
    assert resolution["runtime_effect"] == "observational_only"
    assert resolution["catalog"]["contract_kind"] == "session_aware_tool_catalog"
    assert resolution["decision_summary"]["scope_source"] == "tool_context"
    assert resolution["decision_summary"]["policy_source"] == "no_workflow_routing_policy"
    assert resolution["decision_summary"]["policy_effect_counts"] == {
        "denied": 0,
        "skipped": 0,
        "unavailable": 0,
    }
    assert [event["phase"] for event in resolution["lifecycle"]] == ["scope", "policy", "catalog"]


def test_session_tool_catalog_resolver_summarizes_policy_effects():
    resolution = resolve_session_tool_catalog(
        tool_definitions=[_definition("aws_topology_snapshot")],
        capability_type="diagnosis",
        request_analysis={
            "workflow_routing_policy_resolution": {
                "source": "db",
                "status": "matched",
                "policy_id": "policy-1",
                "policy_version_id": "version-1",
                "matched_group_id": "aws-topology",
                "tool_policy": {
                    "allowlist": ["aws_topology_snapshot", "create_diagram", "bash"],
                    "denylist": ["bash"],
                },
            }
        },
        workflow_contract={"workflow_id": "generic_diagram"},
    )

    assert resolution["decision_summary"]["policy_source"] == "workflow_routing_policy"
    assert resolution["decision_summary"]["routing_policy_id"] == "policy-1"
    assert resolution["decision_summary"]["policy_effect_counts"] == {
        "denied": 1,
        "skipped": 1,
        "unavailable": 1,
    }
