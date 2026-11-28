"""Where a registry tool is offered: in the chat and on the session MCP endpoint (``both``), or on one of them only, each
with its reason. A tool missing here is ``both``; ``tests/tools/misc/test_tool_surfaces.py`` keeps the table to registry names."""

from __future__ import annotations

from dataclasses import dataclass

BOTH = "both"
CHAT_ONLY = "chat_only"
ENGINE_NATIVE = "engine_native"


@dataclass(frozen=True, slots=True)
class ToolSurface:
    kind: str = BOTH
    reason: str = ""


_SERVER_WORKSPACE = ToolSurface(ENGINE_NATIVE, "acts on the platform's server workspace; an engine works in its own "
                                               "folder with its own file, shell, git and code tools")
_BROWSER = ToolSurface(ENGINE_NATIVE, "the engine's runner or device has its own browser")
_MCP_BRIDGE = ToolSurface(ENGINE_NATIVE, "the launcher connects the Workspace's MCP servers to the engine directly")
_TOOL_LOADING = ToolSurface(CHAT_ONLY, "the chat's own tool loading; an MCP client lists and loads tools itself")
_CONVERSATION = ToolSurface(CHAT_ONLY, "the chat's own conversation state; an engine asks and plans in its session")
_WRITE_PLAN = ToolSurface(CHAT_ONLY, "the chat confirms writes with one plan; an MCP write is approved in Octryx")
_WORKFLOW_START = ToolSurface(CHAT_ONLY, "the chat's run start; a session follows or starts runs via workflow_select")
_CHAT_ARTIFACTS = ToolSurface(CHAT_ONLY, "renders an artifact in the chat view, which an engine session has not")
_INFRA_ACTIONS = ToolSurface(CHAT_ONLY, "an infrastructure action, log, config or secret read is never served over MCP, "
                                        "whatever the Workspace policy allows (``mcp_infra_tools.NEVER_SERVED``)")


def _group(surface: ToolSurface, *names: str) -> dict[str, ToolSurface]:
    return dict.fromkeys(names, surface)


TOOL_SURFACES: dict[str, ToolSurface] = {
    **_group(_SERVER_WORKSPACE,
             "bash", "run_cli_command", "start_runtime_process", "poll_runtime_process", "collect_runtime_process",
             "cancel_runtime_process", "python_exec_code", "python_list_variables", "python_close_session",
             "run_saved_python_script", "get_saved_python_script", "list_saved_python_scripts",
             "read_workspace_file", "list_workspace_directory", "glob_workspace_files", "grep_workspace",
             "check_file_syntax", "lint_and_format_workspace", "self_review_workspace_diff", "get_git_diff",
             "list_workspace_git_commits", "git_change_summary", "git_conflict_predictor", "git_coupling_map",
             "git_file_intelligence", "git_function_blame", "git_hotspot_analysis", "git_pr_context",
             "worktree_create", "worktree_diff", "worktree_list", "lsp_diagnostics", "lsp_document_symbols",
             "lsp_find_references", "lsp_go_to_definition", "lsp_hover", "lsp_workspace_symbols", "snapshot_create",
             "snapshot_diff", "snapshot_diff_range", "snapshot_diff_structured", "snapshot_list",
             "bootstrap_workspace_repository", "analyze_workspace_repository", "code_structure_snapshot",
             "run_test_suite", "run_validation_commands", "run_sast_suite", "run_openrewrite_recipe"),
    **_group(_BROWSER, "browser_open_url", "browser_snapshot", "browser_take_screenshot", "browser_click",
             "browser_press", "browser_type", "browser_close"),
    **_group(_MCP_BRIDGE, "list_mcp_servers", "list_mcp_server_tools", "call_mcp_server_tool",
             "list_mcp_server_prompts", "get_mcp_server_prompt", "list_mcp_server_resources",
             "read_mcp_server_resource"),
    **_group(_TOOL_LOADING, "tool_search", "tool_schema_get", "batch", "load_tool_artifact"),
    **_group(_CONVERSATION, "ask_clarification", "todo_read"),
    **_group(_WRITE_PLAN, "propose_write_plan"),
    **_group(_WORKFLOW_START, "select_workflow", "start_workflow"),
    **_group(_INFRA_ACTIONS, "aws_action_operation", "start_aws_ec2_instances", "stop_aws_ec2_instances",
             "start_aws_codepipeline_execution", "get_aws_ec2_logs", "get_aws_lambda_logs", "get_pod_logs",
             "get_k8s_configmap", "list_k8s_secrets"),
    # A diagram returns its XML, which an engine session can use; a document or presentation renders in the chat.
    **_group(_CHAT_ARTIFACTS, "create_document", "create_presentation", "get_presentation_html"),
}


def tool_surface(tool_name: str) -> ToolSurface:
    return TOOL_SURFACES.get(str(tool_name or "").strip(), ToolSurface())


def served_over_mcp(tool_name: str) -> bool:
    return tool_surface(tool_name).kind == BOTH


__all__ = ["BOTH", "CHAT_ONLY", "ENGINE_NATIVE", "TOOL_SURFACES", "ToolSurface", "served_over_mcp", "tool_surface"]
