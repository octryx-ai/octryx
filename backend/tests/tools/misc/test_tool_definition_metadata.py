"""Focused tests for tool definition discovery/filtering metadata."""

from app.services.tool_access_policy import tool_project_policy_decision
from app.tools.capability_requirements import CAPABILITY_DELIVER, tool_required_capability
from app.tools.definitions import (
    get_tool_definition_metadata,
    is_tool_definition_available_for_agent_type,
)
from app.tools.definitions.write_risk import (
    BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES,
    PLATFORM_ADMIN_WRITE_DEFINITION_NAMES,
)


def test_tool_definition_metadata_defaults_and_overrides():
    write_metadata = get_tool_definition_metadata("write_workspace_file")
    batch_metadata = get_tool_definition_metadata("batch")
    plan_exit_metadata = get_tool_definition_metadata("plan_exit")
    default_metadata = get_tool_definition_metadata("list_workspace_directory")

    assert write_metadata.change_only is True
    assert write_metadata.plan_excluded is True
    assert write_metadata.plan_only is False

    assert batch_metadata.change_only is False
    assert batch_metadata.plan_excluded is True
    assert batch_metadata.plan_only is False

    assert plan_exit_metadata.change_only is False
    assert plan_exit_metadata.plan_excluded is False
    assert plan_exit_metadata.plan_only is True

    assert default_metadata.change_only is False
    assert default_metadata.plan_excluded is False
    assert default_metadata.plan_only is False


def test_tool_definition_availability_matches_agent_filters():
    assert is_tool_definition_available_for_agent_type("write_workspace_file", "change") is True
    assert is_tool_definition_available_for_agent_type("write_workspace_file", "admin") is True
    assert is_tool_definition_available_for_agent_type("write_workspace_file", "diagnosis") is False
    assert is_tool_definition_available_for_agent_type("write_workspace_file", "plan") is False

    assert is_tool_definition_available_for_agent_type("batch", "change") is True
    assert is_tool_definition_available_for_agent_type("batch", "diagnosis") is True
    assert is_tool_definition_available_for_agent_type("batch", "plan") is False

    assert is_tool_definition_available_for_agent_type("plan_exit", "plan") is True
    assert is_tool_definition_available_for_agent_type("plan_exit", "change") is False
    assert is_tool_definition_available_for_agent_type("plan_exit", "admin") is False
    assert is_tool_definition_available_for_agent_type("plan_exit", "diagnosis") is False


def _governance(tool_name: str) -> tuple:
    metadata = get_tool_definition_metadata(tool_name)
    decision = tool_project_policy_decision(tool_name, {})
    return (
        metadata.risk,
        metadata.approval_required,
        metadata.mutates_state,
        decision.requires_explicit_allow,
        tool_required_capability(tool_name),
    )


def test_cloud_start_stop_tools_share_one_governance_class():
    # Starting or stopping instances mutates cloud state on every provider: write,
    # approval-required, a high-risk explicit grant, and the ``deliver`` capability.
    expected = ("write", True, True, True, CAPABILITY_DELIVER)
    assert _governance("start_azure_vm") == expected
    assert _governance("stop_azure_vm") == expected
    assert _governance("start_aws_ec2_instances") == _governance("start_azure_vm")
    assert _governance("stop_aws_ec2_instances") == _governance("stop_azure_vm")


def test_built_in_external_writes_need_deliver():
    for tool_name in BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES:
        metadata = get_tool_definition_metadata(tool_name)
        assert metadata.owner_type == "built_in", tool_name
        assert metadata.risk == "write", tool_name
        assert metadata.approval_required is True, tool_name
        assert tool_required_capability(tool_name) == CAPABILITY_DELIVER, tool_name


def test_platform_admin_writes_are_ldap_owned_and_need_a_grant_and_deliver():
    for tool_name in PLATFORM_ADMIN_WRITE_DEFINITION_NAMES:
        metadata = get_tool_definition_metadata(tool_name)
        assert (metadata.owner_type, metadata.connector) == ("connector", "ldap"), tool_name
        assert _governance(tool_name) == ("write", True, True, True, CAPABILITY_DELIVER), tool_name
