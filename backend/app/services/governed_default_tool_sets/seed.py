"""The code-owned seed sets per capability class (``diagnosis.v10``, ``plan.v2``, ``change.v2``, ``admin.v3``)."""

from __future__ import annotations

from .families import (
    _CHAT_CONNECTOR_READ,
    _CONNECTOR_READ,
    _COORDINATION,
    _DELEGATION,
    _DIAGRAMS,
    _KNOWLEDGE,
    _KNOWLEDGE_EXTRAS,
    _KNOWLEDGE_GRAPH,
    _MCP_BRIDGE,
    _OPS_READ,
    _RUN_STEERING,
    _SERVICENOW_READ,
    _SHELL,
    _SKILLS,
    _TOOL_SEARCH,
    _TURN_CONTEXT,
    _WEB,
    _WORK_ITEMS,
    _WORK_LIFECYCLE,
    _WORKFLOW_SELECTION,
)
from .model import GovernedToolSet, ToolFamily

GOVERNED_DEFAULT_TOOL_SETS: dict[str, GovernedToolSet] = {
    tool_set.capability_type: tool_set
    for tool_set in (
        GovernedToolSet(
            capability_type="diagnosis",
            set_id="diagnosis",
            version=10,
            title="Chat and diagnosis",
            description=(
                "Chat: workflow selection, Knowledge and Memory, web, the read tools of the Workspace's active "
                "connectors and the Octryx client's tools; a chat sends only its core tools with full schemas and "
                "the rest by name (tool_search loads them). A chat's writes run under one write plan the person "
                "confirms per request."
            ),
            families=(
                _WORKFLOW_SELECTION,
                _TOOL_SEARCH,
                _TURN_CONTEXT,
                _KNOWLEDGE,
                _SKILLS,
                _WEB,
                _CONNECTOR_READ,
                _CHAT_CONNECTOR_READ,
                _MCP_BRIDGE,
                _SHELL,
                _DELEGATION,
                _WORK_ITEMS,
                _WORK_LIFECYCLE,
                _COORDINATION,
                _RUN_STEERING,
                _KNOWLEDGE_EXTRAS,
                _OPS_READ,
                _SERVICENOW_READ,
                _KNOWLEDGE_GRAPH,
                _DIAGRAMS,
            ),
        ),
        GovernedToolSet(
            capability_type="plan",
            set_id="plan",
            version=2,
            title="Plan",
            description="Read-only exploration for a concrete plan: Knowledge, workspace, code and connector reads.",
            families=(
                ToolFamily("workflow_selection", ("select_workflow", "list_available_workflows")),
                ToolFamily(
                    "turn_context",
                    ("get_current_time", "get_system_context", "instruction_get", "load_tool_artifact"),
                ),
                ToolFamily(
                    "knowledge",
                    (
                        "knowledge_search",
                        "knowledge_read",
                        "knowledge_changes",
                        "knowledge_code_impact",
                        "memory_recall",
                        "search_engineering_knowledge",
                    ),
                ),
                _SKILLS,
                _WEB,
                ToolFamily(
                    "workspace_read",
                    (
                        "list_workspace_directory",
                        "read_workspace_file",
                        "glob_workspace_files",
                        "grep_workspace",
                        "get_git_diff",
                    ),
                ),
                ToolFamily(
                    "code_intelligence",
                    (
                        "code_search",
                        "code_symbol_definition",
                        "code_references",
                        "code_file_outline",
                        "analyze_workspace_repository",
                        "todo_read",
                    ),
                ),
                _CONNECTOR_READ,
            ),
        ),
        GovernedToolSet(
            capability_type="change",
            set_id="change",
            version=2,
            title="Change and coding",
            description=(
                "The coding core: workspace read/write/edit, code search, tests and validation, CLI commands, "
                "sub-agents, Bitbucket/Jira delivery, plus Knowledge and web."
            ),
            families=(
                _WORKFLOW_SELECTION,
                ToolFamily("turn_context", (*_TURN_CONTEXT.tools, "release_context", "todo_read", "todo_write")),
                _KNOWLEDGE,
                ToolFamily(
                    "workspace",
                    (
                        "workspace_select",
                        "bootstrap_workspace_repository",
                        "list_workspace_directory",
                        "read_workspace_file",
                        "write_workspace_file",
                        "edit_workspace_file",
                        "multi_edit_workspace_file",
                        "apply_patch_workspace",
                        "glob_workspace_files",
                        "grep_workspace",
                        "get_git_diff",
                    ),
                ),
                ToolFamily(
                    "code_intelligence",
                    (
                        "code_search",
                        "code_symbol_definition",
                        "code_references",
                        "code_callers",
                        "code_file_outline",
                        "code_context",
                        "analyze_workspace_repository",
                    ),
                ),
                ToolFamily(
                    "verification",
                    (
                        "run_test_suite",
                        "run_validation_commands",
                        "lint_and_format_workspace",
                        "self_review_workspace_diff",
                        # The coding surface runs commands through ``run_cli_command``; ``bash`` stays
                        # out, as under the coding budget.
                        "run_cli_command",
                    ),
                ),
                _DELEGATION,
                ToolFamily(
                    "delivery",
                    (
                        "prepare_bitbucket_repository",
                        "commit_and_push_repository_branch",
                        "create_bitbucket_branch",
                        "create_bitbucket_pull_request",
                        "build_pull_request_description",
                        "get_jira_ticket",
                        "search_jira_tickets",
                        "add_jira_comment",
                    ),
                ),
                _SKILLS,
                _WEB,
            ),
        ),
        GovernedToolSet(
            capability_type="admin",
            set_id="admin",
            version=3,
            title="Admin control plane",
            description=(
                "Platform administration tools plus workflow selection, Knowledge, web, MCP bridge and CLI commands."
            ),
            families=(
                _WORKFLOW_SELECTION,
                _TURN_CONTEXT,
                _KNOWLEDGE,
                ToolFamily(
                    "admin_control",
                    (
                        "admin_platform_status",
                        "admin_get_usage_stats",
                        "admin_view_audit_log",
                        "admin_get_thread_diagnostics",
                        "admin_list_sessions",
                        "admin_list_users",
                        "admin_create_user",
                        "admin_update_user",
                        "admin_delete_user",
                        "admin_list_roles",
                        "admin_create_role",
                        "admin_assign_role",
                        "admin_list_agents",
                        "admin_get_agent",
                        "admin_create_agent",
                        "admin_update_agent",
                        "admin_list_channels",
                        "admin_create_channel",
                        "admin_update_channel",
                        "admin_list_tasks",
                        "admin_update_task",
                        "admin_list_webhooks",
                    ),
                ),
                _SKILLS,
                _WEB,
                _MCP_BRIDGE,
                _SHELL,
            ),
        ),
    )
}
