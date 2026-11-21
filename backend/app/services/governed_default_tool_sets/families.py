"""Tool families shared by the seed sets, each a named group of tools in priority order."""

from __future__ import annotations

from .model import ToolFamily

# ── Families (shared building blocks) ────────────────────────────────────────
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
# "Close PROJ-1..PROJ-6 and list the open PRs" needs the Jira transitions and a PR list; without them
# the model loops on tool_search. Reads are free; chat set only (diagnosis.v10).
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
# The runtime command tool: the diagnosis mode contract asks the model to call it on an explicit
# command request so command policy allows, blocks or asks for approval. ``bash`` stays out: chat
# commands go through the model and this governed tool (no prompt-regex fast path).
_SHELL = ToolFamily("shell", ("run_cli_command",))
_DELEGATION = ToolFamily("delegation", ("spawn_sub_agent", "get_context_from_subthreads"))
# Platform-native work items (Workspaces without Jira plan in chat; the board has no create button).
_WORK_ITEMS = ToolFamily("work_items", ("work_item_create", "work_item_context", "work_item_note"))

# Chat parity with the Octryx client (the chat can do what the client can): the reads the client's MCP server offers
# that the chat lacked. Reads only, no confirmation;
# visibility still drops a connector's tools until the Workspace activates it. Declared last: lowest priority.
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
# The client's work-item lifecycle (gap B): reads free; plans, decisions, transitions and a coding run's start are
# confirmed per call in a chat (``tool_approval_gate``, rule ``chat_platform_write``).
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
# Coordination between agents (gap B group 2): the chat claims, posts and hands off as its own chat-session agent
# (``agent_board.identity.chat_session_identity``). Reads free; claims, posts, acks, handoffs and takeover requests are
# confirmed per call in a chat.
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
# Workflow runs, approvals and tasks (gap B group 3): the client's handlers with the chat as caller. Reads free;
# continuing a run here, a run decision and a run action are confirmed per call.
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
# The client's Knowledge extras (gap B group 4): sources, Workspaces, the entity graph; rating an answer is confirmed.
_KNOWLEDGE_EXTRAS = ToolFamily(
    "knowledge_extras",
    ("knowledge_sources", "knowledge_projects", "entity_search", "entity_neighbors", "knowledge_feedback"),
)
# Session artifacts only (risk read): a draw.io diagram the person sees in the chat.
_DIAGRAMS = ToolFamily("diagrams", ("create_diagram", "edit_diagram", "append_diagram"))
