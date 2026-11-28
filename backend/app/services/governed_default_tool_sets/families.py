"""Tool families shared by the seed sets, each a named group of tools in priority order."""

from __future__ import annotations

from .model import ToolFamily

_WORKFLOW_SELECTION = ToolFamily(
    "workflow_selection", ("select_workflow", "list_available_workflows", "start_workflow")
)
# The chat's door to its deferred tools (``services/chat_deferred_tools``): names in the catalog, schemas on request.
_TOOL_SEARCH = ToolFamily("tool_search", ("tool_search",))
_TURN_CONTEXT = ToolFamily(
    "turn_context",
    ("get_current_time", "get_system_context", "instruction_get", "load_tool_artifact", "ask_clarification"),
)
_KNOWLEDGE = ToolFamily(
    "knowledge",
    (
        "knowledge_search",
        "knowledge_read",
        "knowledge_changes",
        # Read-only evidence that knowledge answers rely on.
        "knowledge_code_impact",
        "memory_recall",
        "memory_remember",
        "search_engineering_knowledge",
    ),
)
_SKILLS = ToolFamily("skills", ("skill_search", "skill_get"))
_WEB = ToolFamily("web", ("web_search", "web_fetch"))
# Read-only tools of the common Workspace connectors; visibility drops a connector's tools until
# the Workspace activates it.
_CONNECTOR_READ = ToolFamily(
    "connector_read",
    (
        "search_jira_tickets",
        "get_jira_ticket",
        "list_jira_projects",
        "search_confluence",
        "get_confluence_page",
        "list_confluence_page_updates",
        "list_recent_bitbucket_commits",
        "get_bitbucket_pull_request",
        "aws_read_operation",
        "list_failed_pods",
        "get_pod_logs",
        "get_k8s_events",
    ),
)
# Without the Jira transitions and a PR list the model loops on tool_search; reads are free, chat set only.
_CHAT_CONNECTOR_READ = ToolFamily(
    "connector_read_more",
    (
        "list_jira_transitions",
        "list_bitbucket_pull_requests",
        "list_github_pull_requests",
        "get_github_pull_request",
        "list_gitlab_merge_requests",
        "get_gitlab_merge_request",
    ),
)
# The lazy bridge to the Workspace's MCP servers (deny-by-default ``mcp_policy``).
_MCP_BRIDGE = ToolFamily("mcp_bridge", ("list_mcp_servers", "list_mcp_server_tools", "call_mcp_server_tool"))
# Explicit command requests go through this governed tool so command policy decides; ``bash`` stays out
_SHELL = ToolFamily("shell", ("run_cli_command",))
# Platform-native work items (Workspaces without Jira plan in chat; the board has no create button).
_WORK_ITEMS = ToolFamily("work_items", ("work_item_create", "work_item_context", "work_item_note"))

# The client's MCP reads the chat lacked; visibility drops a connector's tools until the Workspace activates it.
# Declared last: lowest priority.
_OPS_READ = ToolFamily(
    "ops_read",
    (
        "list_k8s_namespaces",
        "list_k8s_pods",
        "get_k8s_deployments",
        "list_k8s_statefulsets",
        "list_k8s_services",
        "list_k8s_ingresses",
        "list_k8s_nodes",
        "get_k8s_resource_usage",
        "describe_k8s_pod",
        "describe_k8s_deployment",
        "describe_k8s_node",
        "list_aws_eks_clusters",
        "list_aws_ec2_instances",
        "list_aws_rds_instances",
        "list_aws_cloudwatch_alarms",
        "aws_topology_snapshot",
    ),
)
_SERVICENOW_READ = ToolFamily(
    "servicenow_read",
    ("get_servicenow_record", "list_servicenow_records", "list_servicenow_incidents", "list_servicenow_changes"),
)
_KNOWLEDGE_GRAPH = ToolFamily(
    "knowledge_graph", ("graph_neighbors", "config_vs_manual", "ops_chain", "jira_release_status")
)
# Reads free; writes are confirmed per call in a chat (``tool_approval.gate``, rule ``chat_platform_write``).
_WORK_LIFECYCLE = ToolFamily(
    "work_lifecycle",
    (
        "work_item_find",
        "work_item_list",
        "coding_observability",
        "work_item_transition",
        "change_units_plan",
        "change_plan_generate",
        "change_plan_decide",
        "work_item_redeclare",
        "coding_agent_start",
    ),
)
# The chat acts as its own chat-session agent (``agent_board.identity.chat_session_identity``); writes are confirmed.
_COORDINATION = ToolFamily(
    "coordination",
    (
        "board_read",
        "who_is_working_on",
        "agent_presence_list",
        "work_item_handoff_read",
        "work_item_takeover_status",
        "work_item_claim",
        "work_item_release",
        "board_post",
        "board_ack",
        "work_item_handoff_write",
        "work_item_takeover_request",
    ),
)
# Reads free; continuing a run, a run decision and a run action are confirmed per call.
_RUN_STEERING = ToolFamily(
    "run_steering",
    (
        "workflow_catalog",
        "workflow_run_status",
        "approval_get",
        "approval_list",
        "product_run_list",
        "task_list",
        "task_runs",
        "policy_effective",
        "workflow_select",
        "workflow_decide",
        "workflow_action_request",
    ),
)
# Sources, Workspaces, the entity graph; rating an answer is confirmed.
_KNOWLEDGE_EXTRAS = ToolFamily(
    "knowledge_extras",
    ("knowledge_sources", "knowledge_projects", "entity_search", "entity_neighbors", "knowledge_feedback"),
)
# Session artifacts only (risk read): a draw.io diagram the person sees in the chat.
_DIAGRAMS = ToolFamily("diagrams", ("create_diagram", "edit_diagram", "append_diagram"))
