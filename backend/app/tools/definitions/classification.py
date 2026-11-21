"""Closed name sets that classify built-in tool definitions: change-only, plan, core, owner and risk."""

from __future__ import annotations

from .admin import get_admin_definitions
from .bitbucket import get_bitbucket_definitions
from .confluence import get_confluence_definitions
from .connector_ownership import CONNECTOR_BY_OWNED_TOOL
from .connectors import get_connectors_definitions
from .database import get_database_definitions
from .execution import get_execution_definitions
from .getters import DEFINITION_GETTERS
from .git import get_git_definitions
from .github import get_github_definitions
from .gitlab import get_gitlab_definitions
from .jira import get_jira_definitions
from .mcp import get_mcp_definitions
from .workspace import get_workspace_definitions
from .write_risk import WRITE_RISK_DEFINITION_NAMES

# Deliberately NOT change-only: `create_presentation` composes a deck into the
# session workspace from the template's own layouts and executes no
# model-authored code — the same posture as `create_diagram`. Its documentation
# workflows run in diagnosis mode, where change-only tools are not exposed at
# all. `build_presentation_script` stays change-only because it generates AND
# runs a Python script.
CHANGE_ONLY_DEFINITION_NAMES = frozenset(
    {
        "prepare_bitbucket_repository",
        "commit_and_push_repository_branch",
        "write_workspace_file",
        "http_request",
        "build_presentation_script",
        "build_word_template_script",
        "build_excel_template_script",
        "generate_repository_readmes",
        "create_office_document",
        "set_office_property",
        "add_office_element",
        "remove_office_element",
        "fill_office_template",
        "set_excel_cell",
        "create_excel_chart",
        "save_python_script",
        "edit_workspace_file",
        "multi_edit_workspace_file",
        "apply_patch_workspace",
        "todo_write",
        "snapshot_restore",
        "freeze_context",
        "release_context",
        "worktree_commit",
        "worktree_merge",
        "worktree_cleanup",
        "admin_create_user",
        "admin_update_user",
        "admin_delete_user",
        "admin_create_role",
        "admin_assign_role",
        "admin_create_channel",
        "admin_update_channel",
        "admin_update_task",
        "admin_create_agent",
        "admin_update_agent",
        "aws_action_operation",
    }
)

PLAN_EXCLUDED_DEFINITION_NAMES = frozenset(
    {
        *CHANGE_ONLY_DEFINITION_NAMES,
        "ask_clarification",
        "bash",
        "run_cli_command",
        "start_runtime_process",
        "poll_runtime_process",
        "collect_runtime_process",
        "cancel_runtime_process",
        "run_kubectl_command",
        "run_saved_python_script",
        "snapshot_create",
        "worktree_create",
        "batch",
        # Workflow adoption drives execution-phase tool planning; the plan
        # agent must not enter workflows. `list_available_workflows` stays
        # visible everywhere (read-only registry listing).
        "start_workflow",
    }
)

PLAN_ONLY_DEFINITION_NAMES = frozenset({"plan_exit"})

# Tools that are always available directly — not lazy-discovered.
# Everything not in this set is a discoverable (long-tail) tool.
CORE_DEFINITION_NAMES = frozenset(
    {
        # Core skill + knowledge discovery
        "skill_search",
        "skill_get",
        "knowledge_retrieve",
        # Governed Workspace Evidence: citations carry the source link
        "knowledge_search",
        "knowledge_read",
        "knowledge_changes",
        "knowledge_code_impact",
        "memory_remember",
        "memory_recall",
        # Core workspace navigation
        "search_workspace_files",
        "read_workspace_file",
        "list_directory",
        # Core execution
        "bash",
        "run_cli_command",
        # Core planning
        "plan_exit",
        # Core engineering knowledge
        "fetch_and_save_knowledge",
        "build_engineering_knowledge_pack",
        "get_engineering_knowledge_pack",
        "search_engineering_knowledge",
        "get_repository_patterns",
        "get_vulnerability_fix_knowledge",
        "get_pipeline_failure_patterns",
        "get_reviewer_expertise",
        # Core MCP bridge (lazy per-server, but tool is always available)
        "list_mcp_servers",
        "list_mcp_server_tools",
        "call_mcp_server_tool",
        # Core workflow-catalog selection (model-side explicit selection)
        "select_workflow",
        # Core tooling discovery (lazy discovery itself)
        "tool_search",
        "tool_schema_get",
        "instruction_get",
        # Core state + context
        "get_context_checkpoint",
        "set_context_checkpoint",
        "snapshot_create",
        "snapshot_restore",
        "freeze_context",
        "release_context",
        # Core planning / reasoning
        "reasoning",
        "continue_reasoning",
        "stop_reasoning",
        "get_reasoning_trace",
    }
)

GENERIC_CONNECTOR_DEFINITIONS = get_connectors_definitions()
INCIDENT_MANAGEMENT_DEFINITION_NAMES = frozenset(
    {
        "acknowledge",
        "create_incident",
        "escalate",
        "get_escalation_policy",
        "get_schedule",
        "list_oncall",
        "resolve",
        "resolve_incident",
        "update_incident",
    }
)


def _generic_connector_provider(tool_name: str) -> str:
    normalized_name = str(tool_name or "").strip().lower()
    if normalized_name.startswith(
        ("aws_", "list_aws_", "get_aws_", "start_aws_", "stop_aws_", "search_aws_", "invoke_aws_")
    ):
        return "aws"
    if normalized_name.startswith(("azure_", "list_azure_", "get_azure_", "start_azure_", "stop_azure_")):
        return "azure"
    if normalized_name.startswith(("gcp_", "list_gcp_", "get_gcp_")):
        return "gcp"
    if "servicenow" in normalized_name:
        return "servicenow"
    if normalized_name in {"create_incident", "update_incident", "resolve_incident", "escalate", "get_escalation_policy"}:
        return "incident_management"
    return "connector"


CONNECTOR_PROVIDER_BY_TOOL = {
    **{name: "bitbucket" for name in get_bitbucket_definitions()},
    **{name: "confluence" for name in get_confluence_definitions()},
    **{name: "github" for name in get_github_definitions()},
    **{name: "gitlab" for name in get_gitlab_definitions()},
    **{name: "jira" for name in get_jira_definitions()},
    **{name: _generic_connector_provider(name) for name in GENERIC_CONNECTOR_DEFINITIONS},
    **{name: "incident_management" for name in INCIDENT_MANAGEMENT_DEFINITION_NAMES},
    **CONNECTOR_BY_OWNED_TOOL,
}
CONNECTOR_DEFINITION_NAMES = frozenset(CONNECTOR_PROVIDER_BY_TOOL)
DATABASE_DEFINITION_NAMES = frozenset(get_database_definitions())
MCP_DEFINITION_NAMES = frozenset(get_mcp_definitions())
ADMIN_DEFINITION_NAMES = frozenset(get_admin_definitions())
WORKSPACE_DEFINITION_NAMES = frozenset(get_workspace_definitions())
GIT_DEFINITION_NAMES = frozenset(get_git_definitions())
EXECUTION_DEFINITION_NAMES = frozenset(get_execution_definitions())
KNOWN_DEFINITION_NAMES = frozenset(
    name
    for getter in DEFINITION_GETTERS
    for name in getter()
)

# Write risk: the change-only workspace tools plus the closed tables in
# ``write_risk.py``. Everything else that is not admin or unknown resolves to read.
MUTATING_DEFINITION_NAMES = frozenset({*CHANGE_ONLY_DEFINITION_NAMES, *WRITE_RISK_DEFINITION_NAMES})
