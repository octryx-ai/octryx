"""The turn tool policy's externalized guards, repo intelligence and AWS topology guards, and the summary domain fallback defaults."""

from app.agent.core.turn.tool_call_guards import tool_execution_guard_result
from app.services.exec_policy import normalize_exec_policy_config
from app.services.turn_tool_guards import coding_intelligence_guard_result, is_required_summary_domain_tool
from app.services.turn_tool_guards_aws import aws_topology_snapshot_duplicate_guard_result


def test_turn_tool_policy_uses_externalized_guard_defaults() -> None:
    blocked = coding_intelligence_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "backend/app/example.py"},
        turn_tool_history=[],
        capability_type="change",
    )

    assert blocked is not None
    assert blocked["guardrail"] == "coding_prewrite_intelligence_required"
    assert blocked["guard_policy"]["source"] == "exec_policy"
    assert blocked["guard_policy"]["label"] == "Require repository intelligence before code writes"
    assert blocked["exec_policy_action"] == "deny"
    assert "approval_required" not in blocked
    assert "analyze_workspace_repository" in blocked["required_before_write"]


def test_turn_tool_policy_can_disable_configurable_repo_intelligence_guard() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "agent_guard_rules": [
                {
                    "id": "coding_prewrite_intelligence_required",
                    "enabled": False,
                }
            ]
        }
    )

    blocked = coding_intelligence_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "backend/app/example.py"},
        turn_tool_history=[],
        capability_type="change",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is None


def test_turn_tool_policy_can_require_review_for_configurable_repo_intelligence_guard() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "agent_guard_rules": [
                {
                    "id": "coding_prewrite_intelligence_required",
                    "action": "review",
                }
            ]
        }
    )

    blocked = coding_intelligence_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "backend/app/example.py"},
        turn_tool_history=[],
        capability_type="change",
        exec_policy_config=exec_policy_config,
    )

    assert blocked is not None
    assert blocked["guard_policy"]["action"] == "review"
    assert blocked["exec_policy_action"] == "review"
    assert blocked["approval_required"] is True


def test_turn_tool_execution_guard_applies_custom_policy_before_tool_execution() -> None:
    exec_policy_config = normalize_exec_policy_config(
        {
            "custom_tool_guard_rules": [
                {
                    "id": "review-production-write",
                    "label": "Review production write",
                    "tool_names": ["write_workspace_file"],
                    "capability_types": ["change"],
                    "argument_key": "path",
                    "argument_contains": "production",
                    "action": "review",
                    "severity": "critical",
                }
            ]
        }
    )

    blocked = tool_execution_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "config/production.yml", "content": "x"},
        turn_tool_history=[],
        capability_type="change",
        context_snapshot={},
        exec_policy_config=exec_policy_config,
    )

    assert blocked is not None
    assert blocked["guardrail"] == "review-production-write"
    assert blocked["guard_policy"]["source"] == "exec_policy"
    assert blocked["approval_required"] is True


def test_turn_tool_policy_allows_workflow_plan_artifacts_without_repo_intelligence() -> None:
    blocked = coding_intelligence_guard_result(
        tool_name="write_workspace_file",
        tool_args={"path": "ticketing_research_document_plan.json"},
        turn_tool_history=[],
        capability_type="change",
    )

    assert blocked is None


def test_turn_tool_policy_blocks_duplicate_aws_topology_snapshot_with_covered_services() -> None:
    blocked = aws_topology_snapshot_duplicate_guard_result(
        tool_name="aws_topology_snapshot",
        tool_args={"services": ["ec2", "eks"]},
        turn_tool_history=[
            {
                "artifact_id": "artifact-1",
                "tool_name": "aws_topology_snapshot",
                "result": {
                    "scope": {"services_requested": ["sts", "ec2", "eks", "rds"]},
                    "service_summary": {"inventory_services_with_resources": ["ec2", "eks"]},
                },
            }
        ],
    )

    assert blocked is not None
    assert blocked["guardrail"] == "aws_topology_snapshot_already_collected"
    assert blocked["guard_policy"]["label"] == "Avoid duplicate AWS topology snapshots"
    assert blocked["previous_artifact_id"] == "artifact-1"
    assert blocked["service_summary"]["inventory_services_with_resources"] == ["ec2", "eks"]


def test_turn_tool_policy_allows_aws_topology_snapshot_for_uncovered_services() -> None:
    blocked = aws_topology_snapshot_duplicate_guard_result(
        tool_name="aws_topology_snapshot",
        tool_args={"services": ["lambda"]},
        turn_tool_history=[
            {
                "artifact_id": "artifact-1",
                "tool_name": "aws_topology_snapshot",
                "result": {"scope": {"services_requested": ["ec2", "eks"]}},
            }
        ],
    )

    assert blocked is None


def test_summary_domain_policy_uses_externalized_fallback_defaults() -> None:
    assert is_required_summary_domain_tool(
        tool_name="list_recent_bitbucket_commits",
        context_snapshot={"context_plan": {"required_domains": ["bitbucket"]}},
    )
