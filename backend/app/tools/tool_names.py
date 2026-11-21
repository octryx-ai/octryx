"""Single source of truth for all tool name constants.

Pattern from claude-code/src/constants/tools.ts:
- Each name is a typed constant (StrEnum) — never compare raw strings.
- Tool sets (READONLY_TOOLS, etc.) are built from these constants.
- findToolByName() and dispatch logic use ToolName, never literals.
"""

from __future__ import annotations

from enum import StrEnum


class ToolName(StrEnum):
    # ── Workspace / File operations ──────────────────────────────────────────
    WORKSPACE_SELECT = "workspace_select"
    LIST_WORKSPACE_DIRECTORY = "list_workspace_directory"
    READ_WORKSPACE_FILE = "read_workspace_file"
    WRITE_WORKSPACE_FILE = "write_workspace_file"
    EDIT_WORKSPACE_FILE = "edit_workspace_file"
    MULTI_EDIT_WORKSPACE_FILE = "multi_edit_workspace_file"
    APPLY_PATCH_WORKSPACE = "apply_patch_workspace"
    GLOB_WORKSPACE_FILES = "glob_workspace_files"
    GREP_WORKSPACE = "grep_workspace"
    GET_GIT_DIFF = "get_git_diff"
    LIST_WORKSPACE_GIT_COMMITS = "list_workspace_git_commits"
    GET_CURRENT_TIME = "get_current_time"
    WEB_SEARCH = "web_search"

    # ── Git / Repository operations ──────────────────────────────────────────
    BOOTSTRAP_WORKSPACE_REPOSITORY = "bootstrap_workspace_repository"
    PREPARE_BITBUCKET_REPOSITORY = "prepare_bitbucket_repository"
    COMMIT_AND_PUSH_REPOSITORY_BRANCH = "commit_and_push_repository_branch"
    SPAWN_SUB_AGENT = "spawn_sub_agent"
    GET_CONTEXT_FROM_SUBTHREADS = "get_context_from_subthreads"

    # ── Code intelligence ────────────────────────────────────────────────────
    ANALYZE_WORKSPACE_REPOSITORY = "analyze_workspace_repository"
    ANALYZE_CODEBASE_PATTERNS = "analyze_codebase_patterns"
    CODE_STRUCTURE_SNAPSHOT = "code_structure_snapshot"
    CODE_SEARCH = "code_search"
    CODE_SYMBOL_DEFINITION = "code_symbol_definition"
    CODE_REFERENCES = "code_references"
    CODE_CALLERS = "code_callers"
    CODE_IMPACT_ANALYSIS = "code_impact_analysis"
    CODE_FILE_OUTLINE = "code_file_outline"
    CODE_GRAPH_SUMMARY = "code_graph_summary"
    CODE_NODE = "code_node"
    CODE_NEIGHBORS = "code_neighbors"
    CODE_TRACE = "code_trace"
    CODE_GRAPH_STATS = "code_graph_stats"
    CODE_GRAPH_STATUS = "code_graph_status"
    CODE_GOD_NODES = "code_god_nodes"
    CODE_AFFECTED = "code_affected"
    CODE_IMPACT = "code_impact"
    CODE_CALLEES = "code_callees"
    CODE_FILES = "code_files"
    CODE_CONTEXT = "code_context"
    CODE_EXPLORE = "code_explore"
    CODE_INDEX_REPOSITORY = "code_index_repository"
    CODE_INTELLIGENCE_STATUS = "code_intelligence_status"

    # ── Testing / Quality ────────────────────────────────────────────────────
    RUN_TEST_SUITE = "run_test_suite"
    LINT_AND_FORMAT_WORKSPACE = "lint_and_format_workspace"
    SELF_REVIEW_WORKSPACE_DIFF = "self_review_workspace_diff"
    RUN_OPENREWRITE_RECIPE = "run_openrewrite_recipe"
    RUN_SAST_SUITE = "run_sast_suite"
    GET_REPO_CODE_QUALITY_CONFIG = "get_repo_code_quality_config"
    RUN_CLI_COMMAND = "run_cli_command"
    PYTHON_EXEC_CODE = "python_exec_code"
    BUILD_PULL_REQUEST_DESCRIPTION = "build_pull_request_description"
    BATCH = "batch"

    # ── Jira ─────────────────────────────────────────────────────────────────
    CREATE_JIRA_RELEASE_BUNDLE = "create_jira_release_bundle"
    CREATE_JIRA_VERSION = "create_jira_version"
    SEARCH_JIRA_TICKETS = "search_jira_tickets"
    SEARCH_JIRA_USERS = "search_jira_users"
    LIST_JIRA_PROJECTS = "list_jira_projects"
    LIST_JIRA_VERSIONS = "list_jira_versions"

    # ── Knowledge ────────────────────────────────────────────────────────────
    # The one governed Knowledge search (ledger).
    KNOWLEDGE_SEARCH = "knowledge_search"
    SEARCH_ENGINEERING_KNOWLEDGE = "search_engineering_knowledge"
    GET_REPOSITORY_PATTERNS = "get_repository_patterns"
    GET_VULNERABILITY_FIX_KNOWLEDGE = "get_vulnerability_fix_knowledge"
    GET_PIPELINE_FAILURE_PATTERNS = "get_pipeline_failure_patterns"
    GET_REVIEWER_EXPERTISE = "get_reviewer_expertise"
    KNOWLEDGE_READ = "knowledge_read"
    KNOWLEDGE_CHANGES = "knowledge_changes"
    KNOWLEDGE_CODE_IMPACT = "knowledge_code_impact"
    GRAPH_NEIGHBORS = "graph_neighbors"
    CONFIG_VS_MANUAL = "config_vs_manual"
    OPS_CHAIN = "ops_chain"
    JIRA_RELEASE_STATUS = "jira_release_status"
    KNOWLEDGE_EPISODE_SUMMARY = "knowledge_episode_summary"
    LIST_CONFLUENCE_PAGE_UPDATES = "list_confluence_page_updates"
    MEMORY_REMEMBER = "memory_remember"
    MEMORY_RECALL = "memory_recall"
    SKILL_SEARCH = "skill_search"
    SKILL_GET = "skill_get"

    # ── Bitbucket ────────────────────────────────────────────────────────────
    SEARCH_BITBUCKET_USERS = "search_bitbucket_users"
    LIST_RECENT_BITBUCKET_COMMITS = "list_recent_bitbucket_commits"

    # ── MCP ──────────────────────────────────────────────────────────────────
    LIST_MCP_SERVERS = "list_mcp_servers"
    LIST_MCP_SERVER_TOOLS = "list_mcp_server_tools"
    CALL_MCP_SERVER_TOOL = "call_mcp_server_tool"
    LIST_MCP_SERVER_RESOURCES = "list_mcp_server_resources"
    READ_MCP_SERVER_RESOURCE = "read_mcp_server_resource"
    LIST_MCP_SERVER_PROMPTS = "list_mcp_server_prompts"
    GET_MCP_SERVER_PROMPT = "get_mcp_server_prompt"

    # ── Misc ─────────────────────────────────────────────────────────────────
    GET_SHAPE_LIBRARY = "get_shape_library"
    LOAD_TOOL_ARTIFACT = "load_tool_artifact"
    RELEASE_CONTEXT = "release_context"


# ── Tool sets (mirrors claude-code/src/constants/tools.ts) ───────────────────
# Use frozenset[ToolName] — never bare string sets.

# Tools that only read, never write — safe to run concurrently.
READONLY_TOOL_NAMES: frozenset[ToolName] = frozenset(
    {
        ToolName.LIST_WORKSPACE_DIRECTORY,
        ToolName.READ_WORKSPACE_FILE,
        ToolName.GLOB_WORKSPACE_FILES,
        ToolName.GREP_WORKSPACE,
        ToolName.GET_GIT_DIFF,
        ToolName.LIST_WORKSPACE_GIT_COMMITS,
        ToolName.GET_CURRENT_TIME,
        ToolName.WEB_SEARCH,
        ToolName.CODE_SEARCH,
        ToolName.CODE_SYMBOL_DEFINITION,
        ToolName.CODE_REFERENCES,
        ToolName.CODE_CALLERS,
        ToolName.CODE_FILE_OUTLINE,
        ToolName.CODE_GRAPH_SUMMARY,
        ToolName.CODE_NODE,
        ToolName.CODE_NEIGHBORS,
        ToolName.CODE_TRACE,
        ToolName.CODE_GRAPH_STATS,
        ToolName.CODE_GRAPH_STATUS,
        ToolName.CODE_GOD_NODES,
        ToolName.CODE_AFFECTED,
        ToolName.CODE_IMPACT,
        ToolName.CODE_CALLEES,
        ToolName.CODE_FILES,
        ToolName.CODE_CONTEXT,
        ToolName.CODE_EXPLORE,
        ToolName.CODE_INTELLIGENCE_STATUS,
        ToolName.GET_REPO_CODE_QUALITY_CONFIG,
        ToolName.LIST_MCP_SERVERS,
        ToolName.LIST_MCP_SERVER_TOOLS,
        ToolName.LIST_MCP_SERVER_RESOURCES,
        ToolName.READ_MCP_SERVER_RESOURCE,
        ToolName.LIST_MCP_SERVER_PROMPTS,
        ToolName.GET_MCP_SERVER_PROMPT,
        ToolName.KNOWLEDGE_SEARCH,
        ToolName.SEARCH_ENGINEERING_KNOWLEDGE,
        ToolName.GET_REPOSITORY_PATTERNS,
        ToolName.GET_VULNERABILITY_FIX_KNOWLEDGE,
        ToolName.GET_PIPELINE_FAILURE_PATTERNS,
        ToolName.GET_REVIEWER_EXPERTISE,
        ToolName.KNOWLEDGE_READ,
        ToolName.KNOWLEDGE_CHANGES,
        ToolName.KNOWLEDGE_CODE_IMPACT,
        ToolName.JIRA_RELEASE_STATUS,
        ToolName.MEMORY_RECALL,
        ToolName.SKILL_SEARCH,
        ToolName.SKILL_GET,
        ToolName.LIST_RECENT_BITBUCKET_COMMITS,
        ToolName.SEARCH_BITBUCKET_USERS,
        ToolName.GET_SHAPE_LIBRARY,
        ToolName.SEARCH_JIRA_TICKETS,
        ToolName.SEARCH_JIRA_USERS,
        ToolName.LIST_JIRA_PROJECTS,
        ToolName.LIST_JIRA_VERSIONS,
        ToolName.GET_CONTEXT_FROM_SUBTHREADS,
    }
)

# Turn meta tools — bookkeeping, not domain actions.
TURN_META_TOOL_NAMES: frozenset[ToolName] = frozenset(
    {
        ToolName.LOAD_TOOL_ARTIFACT,
        ToolName.RELEASE_CONTEXT,
    }
)

# Tools that form the coding agent's core capability surface.
CODING_CORE_TOOL_NAMES: tuple[ToolName, ...] = (
    ToolName.WORKSPACE_SELECT,
    ToolName.BOOTSTRAP_WORKSPACE_REPOSITORY,
    ToolName.LIST_WORKSPACE_DIRECTORY,
    ToolName.READ_WORKSPACE_FILE,
    ToolName.WRITE_WORKSPACE_FILE,
    ToolName.EDIT_WORKSPACE_FILE,
    ToolName.MULTI_EDIT_WORKSPACE_FILE,
    ToolName.APPLY_PATCH_WORKSPACE,
    ToolName.GLOB_WORKSPACE_FILES,
    ToolName.GREP_WORKSPACE,
    ToolName.GET_GIT_DIFF,
    ToolName.LIST_WORKSPACE_GIT_COMMITS,
    ToolName.CODE_INTELLIGENCE_STATUS,
    ToolName.CODE_INDEX_REPOSITORY,
    ToolName.CODE_SEARCH,
    ToolName.CODE_SYMBOL_DEFINITION,
    ToolName.CODE_REFERENCES,
    ToolName.CODE_CALLERS,
    ToolName.CODE_FILE_OUTLINE,
    ToolName.CODE_GRAPH_SUMMARY,
    ToolName.CODE_NODE,
    ToolName.CODE_NEIGHBORS,
    ToolName.CODE_TRACE,
    ToolName.CODE_GRAPH_STATS,
    ToolName.CODE_GRAPH_STATUS,
    ToolName.CODE_GOD_NODES,
    ToolName.CODE_AFFECTED,
    ToolName.CODE_IMPACT,
    ToolName.CODE_CALLEES,
    ToolName.CODE_FILES,
    ToolName.CODE_CONTEXT,
    ToolName.CODE_EXPLORE,
    ToolName.CODE_IMPACT_ANALYSIS,
    ToolName.ANALYZE_WORKSPACE_REPOSITORY,
    ToolName.ANALYZE_CODEBASE_PATTERNS,
    ToolName.RUN_TEST_SUITE,
    ToolName.LINT_AND_FORMAT_WORKSPACE,
    ToolName.SELF_REVIEW_WORKSPACE_DIFF,
    ToolName.RUN_OPENREWRITE_RECIPE,
    ToolName.RUN_SAST_SUITE,
    ToolName.GET_REPO_CODE_QUALITY_CONFIG,
    ToolName.RUN_CLI_COMMAND,
    ToolName.PYTHON_EXEC_CODE,
    ToolName.SEARCH_ENGINEERING_KNOWLEDGE,
    ToolName.GET_REPOSITORY_PATTERNS,
    ToolName.GET_VULNERABILITY_FIX_KNOWLEDGE,
    ToolName.GET_PIPELINE_FAILURE_PATTERNS,
    ToolName.GET_REVIEWER_EXPERTISE,
    ToolName.SPAWN_SUB_AGENT,
    ToolName.GET_CONTEXT_FROM_SUBTHREADS,
)

# Minimal tool set for general (non-coding) agent tasks.
GENERAL_CORE_TOOL_NAMES: tuple[ToolName, ...] = (
    ToolName.WORKSPACE_SELECT,
    ToolName.LIST_WORKSPACE_DIRECTORY,
    ToolName.READ_WORKSPACE_FILE,
    ToolName.WRITE_WORKSPACE_FILE,
    ToolName.GLOB_WORKSPACE_FILES,
    ToolName.GREP_WORKSPACE,
    ToolName.SEARCH_JIRA_TICKETS,
    ToolName.SEARCH_JIRA_USERS,
    ToolName.LIST_JIRA_VERSIONS,
    ToolName.LIST_RECENT_BITBUCKET_COMMITS,
    ToolName.SEARCH_ENGINEERING_KNOWLEDGE,
    ToolName.GET_REPOSITORY_PATTERNS,
    ToolName.GET_VULNERABILITY_FIX_KNOWLEDGE,
    ToolName.GET_PIPELINE_FAILURE_PATTERNS,
    ToolName.GET_REVIEWER_EXPERTISE,
    ToolName.WEB_SEARCH,
)

# Code preflight tools — used before coding turns begin.
CODING_PREFLIGHT_TOOL_NAMES: frozenset[ToolName] = frozenset(
    {
        ToolName.BOOTSTRAP_WORKSPACE_REPOSITORY,
        ToolName.PREPARE_BITBUCKET_REPOSITORY,
        ToolName.ANALYZE_WORKSPACE_REPOSITORY,
        ToolName.ANALYZE_CODEBASE_PATTERNS,
        ToolName.CODE_SEARCH,
        ToolName.CODE_SYMBOL_DEFINITION,
        ToolName.CODE_REFERENCES,
        ToolName.CODE_CALLERS,
        ToolName.CODE_IMPACT_ANALYSIS,
        ToolName.CODE_FILE_OUTLINE,
        ToolName.CODE_CONTEXT,
        ToolName.CODE_EXPLORE,
        ToolName.CODE_GRAPH_STATUS,
    }
)
