"""Custom exec policy tool guards: block, review and audit actions, nested conditions, exceptions and operators."""

from app.services.exec_policy import normalize_exec_policy_config
from app.services.turn_tool_guards import (
    custom_exec_policy_tool_guard_decisions,
    custom_exec_policy_tool_guard_result,
)


def test_custom_exec_policy_tool_guard_blocks_matching_tool_args() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "no-production-write",
                    "label": "No production writes",
                    "tool_names": ["write_workspace_file"],
                    "capability_types": ["change"],
                    "argument_key": "path",
                    "argument_contains": "production",
                    "action": "block",
                    "severity": "critical",
                }
            ]
        }
    )

    blocked = custom_exec_policy_tool_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "config/production.yml", "content": "x"},
        capability_type="change",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is not None
    assert blocked["guardrail"] == "no-production-write"
    assert blocked["guard_policy"]["category"] == "custom"
    assert blocked["exec_policy_action"] == "deny"
    assert blocked["exec_policy_risk"] == "critical"
    assert blocked["matched_guard"]["argument_key"] == "path"


def test_custom_exec_policy_tool_guard_requires_review_for_matching_tool_args() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "review-shell",
                    "label": "Review shell",
                    "tool_names": ["bash"],
                    "argument_contains": "kubectl",
                    "action": "review",
                    "severity": "high",
                }
            ]
        }
    )

    blocked = custom_exec_policy_tool_guard_result(
        tool_name="bash",
        tool_args={"command": "kubectl get pods"},
        capability_type="diagnosis",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is not None
    assert blocked["guard_policy"]["action"] == "review"
    assert blocked["approval_required"] is True
    assert blocked["exec_policy_action"] == "review"


def test_custom_exec_policy_tool_guard_audit_action_matches_without_blocking() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "audit-shell",
                    "label": "Audit shell",
                    "tool_names": ["bash"],
                    "argument_contains": "kubectl",
                    "action": "audit",
                    "severity": "medium",
                }
            ]
        }
    )

    decisions = custom_exec_policy_tool_guard_decisions(
        tool_name="bash",
        tool_args={"command": "kubectl get pods"},
        capability_type="diagnosis",
        exec_policy_config=exec_policy_config,
    )
    blocked = custom_exec_policy_tool_guard_result(
        tool_name="bash",
        tool_args={"command": "kubectl get pods"},
        capability_type="diagnosis",
        exec_policy_config=exec_policy_config,
    )

    assert [decision["action"] for decision in decisions] == ["audit"]
    assert decisions[0]["guard_id"] == "audit-shell"
    assert blocked is None


def test_custom_exec_policy_tool_guard_ignores_non_matching_tool_args() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "no-production-write",
                    "label": "No production writes",
                    "tool_names": ["write_workspace_file"],
                    "argument_key": "path",
                    "argument_contains": "production",
                }
            ]
        }
    )

    blocked = custom_exec_policy_tool_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "config/development.yml"},
        capability_type="change",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is None


def test_custom_exec_policy_tool_guard_matches_nested_all_any_not_conditions() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "review-unapproved-production-write",
                    "label": "Review unapproved production write",
                    "tool_names": ["write_workspace_file"],
                    "conditions": {
                        "all": [
                            {"field": "tool.capability_type", "operator": "equals", "value": "change"},
                            {
                                "any": [
                                    {"field": "args.path", "operator": "matches_pattern", "value": "*production*"},
                                    {
                                        "field": "args.metadata.environment",
                                        "operator": "in",
                                        "values": ["prod", "dr"],
                                    },
                                ]
                            },
                            {"not": {"field": "args.approved_change_id", "operator": "exists"}},
                        ]
                    },
                    "action": "review",
                    "severity": "critical",
                }
            ]
        }
    )

    blocked = custom_exec_policy_tool_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "config/production.yml", "metadata": {"environment": "test"}},
        capability_type="change",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is not None
    assert blocked["guardrail"] == "review-unapproved-production-write"
    assert blocked["approval_required"] is True
    assert blocked["matched_guard"]["conditions"]["all"][0]["field"] == "tool.capability_type"


def test_custom_exec_policy_tool_guard_allows_condition_when_exception_exists() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "review-unapproved-production-write",
                    "tool_names": ["write_workspace_file"],
                    "conditions": {
                        "all": [
                            {"field": "args.path", "operator": "matches_pattern", "value": "*production*"},
                            {"not": {"field": "args.approved_change_id", "operator": "exists"}},
                        ]
                    },
                    "action": "review",
                }
            ]
        }
    )

    blocked = custom_exec_policy_tool_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "config/production.yml", "approved_change_id": "CHG-42"},
        capability_type="change",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is None


def test_custom_exec_policy_tool_guard_matches_list_and_numeric_operators() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "block-risky-bulk-network-write",
                    "conditions": {
                        "all": [
                            {"field": "args.tags", "operator": "any_in", "values": ["network", "firewall"]},
                            {"field": "args.change_count", "operator": "greater_than_or_equals", "value": 10},
                        ]
                    },
                    "action": "block",
                    "severity": "high",
                }
            ]
        }
    )

    blocked = custom_exec_policy_tool_guard_result(
        tool_name="apply_change",
        tool_args={"tags": ["database", "network"], "change_count": 12},
        capability_type="change",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is not None
    assert blocked["guardrail"] == "block-risky-bulk-network-write"
    assert blocked["exec_policy_action"] == "deny"
