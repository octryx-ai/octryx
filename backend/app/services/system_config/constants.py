"""Shared constants for system configuration settings."""

from __future__ import annotations

from ...config import get_settings
from ...runtime_limits import (
    DEFAULT_APPROX_CHARS_PER_TOKEN,
    DEFAULT_EXTENDED_COMPLETION_TOKENS,
    DEFAULT_LLM_CACHE_TOOLS_TTL_SECONDS,
    DEFAULT_LLM_CACHE_TTL_SECONDS,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    DEFAULT_TRACE_MAX_DICT_ITEMS,
    DEFAULT_TRACE_MAX_LIST_ITEMS,
    DEFAULT_TRACE_MAX_STRING,
    MAX_APPROX_CHARS_PER_TOKEN,
    MAX_COMPLETION_TOKENS,
    MAX_LLM_CACHE_TTL_SECONDS,
    MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MAX_TRACE_MAX_DICT_ITEMS,
    MAX_TRACE_MAX_LIST_ITEMS,
    MAX_TRACE_MAX_STRING,
    MIN_APPROX_CHARS_PER_TOKEN,
    MIN_COMPLETION_TOKENS,
    MIN_LLM_CACHE_TTL_SECONDS,
    MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MIN_TRACE_MAX_DICT_ITEMS,
    MIN_TRACE_MAX_LIST_ITEMS,
    MIN_TRACE_MAX_STRING,
)

AGENT_AUTH_LOGIN_MODE_KEY = "agent.auth_login_mode"
AGENT_DEFAULT_COMPLETION_TOKENS_KEY = "agent.default_completion_tokens"
AGENT_EXTENDED_COMPLETION_TOKENS_KEY = "agent.extended_completion_tokens"
AGENT_APPROX_CHARS_PER_TOKEN_KEY = "agent.approx_chars_per_token"
AGENT_TRACE_MAX_STRING_KEY = "agent.trace_max_string"
AGENT_TRACE_MAX_LIST_ITEMS_KEY = "agent.trace_max_list_items"
AGENT_TRACE_MAX_DICT_ITEMS_KEY = "agent.trace_max_dict_items"
AGENT_SAVED_SCRIPT_MAX_OUTPUT_CHARS_KEY = "agent.saved_script_max_output_chars"
AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS_KEY = "agent.runtime_request_timeout_seconds"
AGENT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES_KEY = "agent.runtime_unreachable_retry_max_retries"
AGENT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS_KEY = "agent.runtime_unreachable_retry_pause_seconds"
AGENT_RUNTIME_FALLBACK_MODE_KEY = "agent.runtime_fallback_mode"
AGENT_SESSION_COST_LIMIT_USD_KEY = "agent.session_cost_limit_usd"
AGENT_REQUEST_COST_LIMIT_USD_KEY = "agent.request_cost_limit_usd"
AGENT_LLM_CACHE_TTL_SECONDS_KEY = "agent.llm_cache_ttl_seconds"
AGENT_LLM_CACHE_TOOLS_TTL_SECONDS_KEY = "agent.llm_cache_tools_ttl_seconds"
AGENT_LLM_TOOL_PLANNER_TRACE_CALL_ENABLED_KEY = "agent.llm_tool_planner_trace_call_enabled"
AGENT_LLM_TOOL_PLANNER_MAX_TOKENS_KEY = "agent.llm_tool_planner_max_tokens"
AGENT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS_KEY = "agent.llm_tool_planner_timeout_seconds"
AGENT_TOOL_DOMAIN_CONFIG_KEY = "agent.tool_domain_config"
AGENT_SYSTEM_PROMPT_VARIANT_CONFIG_KEY = "agent.system_prompt.variant_map"
AGENT_EXECUTION_RUNTIME_PROVIDER_KEY = "agent.execution_runtime_provider"
AGENT_EXECUTION_RUNTIME_DOCKER_IMAGE_KEY = "agent.execution_runtime_docker_image"
AGENT_EXECUTION_RUNTIME_DOCKER_NETWORK_MODE_KEY = "agent.execution_runtime_docker_network_mode"
AGENT_EXECUTION_RUNTIME_ALLOW_HOST_FALLBACK_KEY = "agent.execution_runtime_allow_host_fallback"
AGENT_EXECUTION_RUNTIME_SANDBOX_MODE_KEY = "agent.execution_runtime_sandbox_mode"
AGENT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB_KEY = "agent.execution_runtime_docker_memory_mb"
AGENT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT_KEY = "agent.execution_runtime_docker_pids_limit"
AGENT_WORKER_TRUST_DELTAS_KEY = "agent.worker_trust_deltas"
AGENT_SESSION_WORKSPACE_BASE_DIR_KEY = "agent.session_workspace_base_dir"
AGENT_SESSION_WORKSPACE_MAX_AGE_HOURS_KEY = "agent.session_workspace_max_age_hours"
AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY = "agent.session_workspace_storage_backend"
AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY = "agent.session_workspace_storage_bucket"
AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY = "agent.session_workspace_storage_prefix"
AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY = "agent.session_workspace_sync_excluded_dirs"
AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY = "agent.session_workspace_sync_excluded_globs"
AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY = "agent.session_workspace_sync_max_file_size_bytes"
AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY = "agent.session_workspace_sync_max_file_count"
AGENT_DISK_HYGIENE_CORP_IDENTITY_CACHE_MIN_AGE_HOURS_KEY = "agent.disk_hygiene.corp_identity_cache_min_age_hours"
AGENT_DISK_HYGIENE_OFFICE_IMPORT_STALE_MIN_AGE_HOURS_KEY = "agent.disk_hygiene.office_import_stale_min_age_hours"
AGENT_WORKER_TRUST_DELTA_SUCCESS_KEY = "agent.worker_trust_delta.success"
AGENT_WORKER_TRUST_DELTA_FAILURE_KEY = "agent.worker_trust_delta.failure"
AGENT_WORKER_TRUST_DELTA_UNNECESSARY_ESCALATION_KEY = "agent.worker_trust_delta.unnecessary_escalation"
AGENT_WORKER_TRUST_DELTA_CORRECT_ESCALATION_KEY = "agent.worker_trust_delta.correct_escalation"
AGENT_WORKER_TRUST_DELTA_HUMAN_OVERRIDDEN_KEY = "agent.worker_trust_delta.human_overridden"
AGENT_WORKER_TRUST_DELTA_HUMAN_APPROVED_KEY = "agent.worker_trust_delta.human_approved"
AGENT_OFFICE_TEMPLATE_LIBRARY_KEY = "agent.office_template_library"
AGENT_SECURITY_ANALYZER_CHAIN_KEY = "agent.security_analyzer_chain"
AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY = "agent.llm_security_analyzer_timeout_seconds"
AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY = "agent.llm_security_analyzer_review_threshold"
AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY = "agent.llm_security_analyzer_deny_threshold"
AGENT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD_KEY = "agent.stuck_loop_tool_repeat_threshold"
AGENT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD_KEY = "agent.stuck_loop_blocked_tool_threshold"
AGENT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD_KEY = "agent.stuck_loop_repeated_jira_threshold"
AGENT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD_KEY = "agent.stuck_loop_no_tool_duplicate_threshold"
AGENT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD_KEY = "agent.stuck_loop_summary_repeat_threshold"
AGENT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD_KEY = "agent.stuck_loop_no_tool_similarity_threshold"
AGENT_ELASTIC_ITERATION_ENABLED_KEY = "agent.elastic_iteration_enabled"
AGENT_ELASTIC_ITERATION_MAX_BONUS_KEY = "agent.elastic_iteration_max_bonus"
AGENT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD_KEY = "agent.elastic_iteration_unique_tool_threshold"
ARTIFACT_STORE_BACKEND_KEY = "artifact_store.backend"
ARTIFACT_STORE_BUCKET_KEY = "artifact_store.bucket"
ARTIFACT_STORE_PREFIX_KEY = "artifact_store.prefix"
ARTIFACT_STORE_S3_REGION_KEY = "artifact_store.s3_region"
ARTIFACT_STORE_S3_ENDPOINT_URL_KEY = "artifact_store.s3_endpoint_url"

DEFAULT_EXECUTION_RUNTIME_PROVIDER = "host"
DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE = "python:3.11-slim"
DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE = "none"
DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE = "compat"
DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB = 512
DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT = 256
DEFAULT_SESSION_WORKSPACE_MAX_AGE_HOURS = 24
DEFAULT_DISK_HYGIENE_CORP_IDENTITY_CACHE_MIN_AGE_HOURS = 24
DEFAULT_DISK_HYGIENE_OFFICE_IMPORT_STALE_MIN_AGE_HOURS = 72
DEFAULT_SECURITY_ANALYZER_CHAIN = ["exec_policy", "secret_access", "command_guardrail"]
DEFAULT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS = 8
DEFAULT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD = 40
DEFAULT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD = 80
DEFAULT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD = 5
DEFAULT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD = 2
DEFAULT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD = 4
DEFAULT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD = 2
DEFAULT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD = 1
DEFAULT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD = 0.72
DEFAULT_ELASTIC_ITERATION_ENABLED = True
DEFAULT_ELASTIC_ITERATION_MAX_BONUS = 6
DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD = 2
DEFAULT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES = 2
DEFAULT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS = 3
# Defaults must let the work run: a backstop against runaway spend, not a brake on
# normal work. Stored platform or Workspace values stay as they are; runs keep their own budget.
DEFAULT_AGENT_SESSION_COST_LIMIT_USD = 50.0
DEFAULT_AGENT_REQUEST_COST_LIMIT_USD = 10.0
DEFAULT_LLM_TOOL_PLANNER_TRACE_CALL_ENABLED = False
DEFAULT_LLM_TOOL_PLANNER_MAX_TOKENS = 900
DEFAULT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS = 30
MIN_LLM_TOOL_PLANNER_MAX_TOKENS = 128
MIN_LLM_TOOL_PLANNER_TIMEOUT_SECONDS = 1

_DEFAULT_DOMAIN_TOOL_ALLOWLISTS: dict[str, list[str]] | None = None

# Map domain → keywords that identify tools for that domain.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "jira": ["jira"],
    "bitbucket": ["bitbucket"],
    "confluence": ["confluence"],
    "observability": ["grafana", "prometheus", "loki"],
    "kubernetes": ["k8s"],
    "mcp": ["mcp"],
    "aws": ["aws_", "_aws_"],
    "azure": ["azure"],
    "gcp": ["gcp"],
}


def get_domain_tool_allowlists() -> dict[str, list[str]]:
    """Lazily auto-discover ALL connector tools from definitions by naming convention.

    Uses the definitions registry (pure dicts, no circular imports) instead of
    the tool class registry to avoid circular dependency chains.
    """
    global _DEFAULT_DOMAIN_TOOL_ALLOWLISTS
    if _DEFAULT_DOMAIN_TOOL_ALLOWLISTS is not None:
        return _DEFAULT_DOMAIN_TOOL_ALLOWLISTS

    # Import from definitions modules (pure dicts, no tool class imports)
    from ...tools.definitions.bitbucket import get_bitbucket_definitions
    from ...tools.definitions.confluence import get_confluence_definitions
    from ...tools.definitions.connectors import get_connectors_definitions
    from ...tools.definitions.grafana import get_grafana_definitions
    from ...tools.definitions.jira import get_jira_definitions
    from ...tools.definitions.kubernetes import get_kubernetes_definitions
    from ...tools.definitions.loki import get_loki_definitions
    from ...tools.definitions.mcp import get_mcp_definitions
    from ...tools.definitions.prometheus import get_prometheus_definitions

    # Collect all tool names from definition registries
    all_tool_names: set[str] = set()
    for getter in (
        get_connectors_definitions,
        get_jira_definitions,
        get_bitbucket_definitions,
        get_confluence_definitions,
        get_grafana_definitions,
        get_prometheus_definitions,
        get_loki_definitions,
        get_kubernetes_definitions,
        get_mcp_definitions,
    ):
        all_tool_names.update(getter().keys())

    result: dict[str, list[str]] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        tools = sorted(
            name for name in all_tool_names
            if any(kw in name for kw in keywords)
        )
        if tools:
            result[domain] = tools

    _DEFAULT_DOMAIN_TOOL_ALLOWLISTS = result
    return result


DEFAULT_SUMMARY_DOMAIN_TOOL_ALLOWLISTS: dict[str, list[str]] = {
    "jira": [
        "list_jira_projects",
        "search_jira_tickets",
        "get_jira_ticket",
    ],
    "bitbucket": [
        "list_recent_bitbucket_commits",
    ],
    "confluence": [
        "search_confluence",
        # The recorded changes feed of the Confluence Source Sync (explicit needs_configuration without it).
        "list_confluence_page_updates",
    ],
    "observability": [
        "list_grafana_alerts",
        "read_grafana_alert",
        "query_prometheus",
        "query_loki",
    ],
    "kubernetes": [
        "get_k8s_events",
        "get_pod_logs",
        "list_failed_pods",
        "get_k8s_deployments",
        "list_k8s_namespaces",
        "list_k8s_pods",
        "describe_k8s_pod",
        "list_k8s_services",
        "list_k8s_nodes",
        "get_k8s_configmap",
        "list_k8s_ingresses",
        "get_k8s_resource_usage",
        "describe_k8s_deployment",
        "describe_k8s_node",
        "list_k8s_statefulsets",
        "list_k8s_daemonsets",
        "list_k8s_jobs",
        "list_k8s_cronjobs",
        "list_k8s_pvcs",
        "list_k8s_endpoints",
        "list_k8s_network_policies",
        "list_k8s_hpas",
        "list_k8s_secrets",
    ],
    "mcp": [
        "list_mcp_servers",
        "list_mcp_server_tools",
        "call_mcp_server_tool",
        "list_mcp_server_resources",
        "read_mcp_server_resource",
        "list_mcp_server_prompts",
        "get_mcp_server_prompt",
    ],
}

DEFAULT_SUMMARY_TOOL_DOMAINS: dict[str, set[str]] = {
    "list_jira_projects": {"jira"},
    "search_jira_tickets": {"jira"},
    "get_jira_ticket": {"jira"},
    "list_recent_bitbucket_commits": {"bitbucket"},
    "list_bitbucket_repositories": {"bitbucket"},
    "list_bitbucket_commits": {"bitbucket"},
    "get_bitbucket_commit_changes": {"bitbucket"},
    "list_bitbucket_pull_requests": {"bitbucket"},
    "get_bitbucket_pull_request": {"bitbucket"},
    "get_bitbucket_diff": {"bitbucket"},
    "list_confluence_pages": {"confluence"},
    "get_confluence_page": {"confluence"},
    "search_confluence": {"confluence"},
    "list_confluence_page_updates": {"confluence"},
    "list_grafana_alerts": {"observability"},
    "read_grafana_alert": {"observability"},
    "query_prometheus": {"observability"},
    "query_loki": {"observability"},
    "get_k8s_events": {"kubernetes"},
    "get_pod_logs": {"kubernetes"},
    "list_failed_pods": {"kubernetes"},
    "get_k8s_deployments": {"kubernetes"},
    "list_k8s_namespaces": {"kubernetes"},
    "list_k8s_pods": {"kubernetes"},
    "describe_k8s_pod": {"kubernetes"},
    "list_k8s_services": {"kubernetes"},
    "list_k8s_nodes": {"kubernetes"},
    "get_k8s_configmap": {"kubernetes"},
    "list_k8s_ingresses": {"kubernetes"},
    "get_k8s_resource_usage": {"kubernetes"},
    "describe_k8s_deployment": {"kubernetes"},
    "describe_k8s_node": {"kubernetes"},
    "list_k8s_statefulsets": {"kubernetes"},
    "list_k8s_daemonsets": {"kubernetes"},
    "list_k8s_jobs": {"kubernetes"},
    "list_k8s_cronjobs": {"kubernetes"},
    "list_k8s_pvcs": {"kubernetes"},
    "list_k8s_endpoints": {"kubernetes"},
    "list_k8s_network_policies": {"kubernetes"},
    "list_k8s_hpas": {"kubernetes"},
    "list_k8s_secrets": {"kubernetes"},
}

DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS: dict[str, set[str]] = {
    "jira": {"list_jira_projects", "search_jira_tickets", "get_jira_ticket"},
    "bitbucket": {"list_recent_bitbucket_commits"},
    "confluence": {"search_confluence", "list_confluence_page_updates"},
    "observability": {"list_grafana_alerts", "read_grafana_alert", "query_prometheus", "query_loki"},
    "kubernetes": {
        "get_k8s_events",
        "get_pod_logs",
        "list_failed_pods",
        "get_k8s_deployments",
        "list_k8s_namespaces",
        "list_k8s_pods",
        "describe_k8s_pod",
        "list_k8s_services",
        "list_k8s_nodes",
        "get_k8s_configmap",
        "list_k8s_ingresses",
        "get_k8s_resource_usage",
        "describe_k8s_deployment",
        "describe_k8s_node",
        "list_k8s_statefulsets",
        "list_k8s_daemonsets",
        "list_k8s_jobs",
        "list_k8s_cronjobs",
        "list_k8s_pvcs",
        "list_k8s_endpoints",
        "list_k8s_network_policies",
        "list_k8s_hpas",
        "list_k8s_secrets",
    },
}

settings = get_settings()

_TOOL_DOMAIN_EXPORTS = (
    DEFAULT_SUMMARY_DOMAIN_SATISFYING_TOOLS,
    DEFAULT_SUMMARY_DOMAIN_TOOL_ALLOWLISTS,
    DEFAULT_SUMMARY_TOOL_DOMAINS,
)
_RUNTIME_LIMIT_EXPORTS = (
    DEFAULT_APPROX_CHARS_PER_TOKEN,
    DEFAULT_EXTENDED_COMPLETION_TOKENS,
    DEFAULT_LLM_CACHE_TOOLS_TTL_SECONDS,
    DEFAULT_LLM_CACHE_TTL_SECONDS,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    DEFAULT_TRACE_MAX_DICT_ITEMS,
    DEFAULT_TRACE_MAX_LIST_ITEMS,
    DEFAULT_TRACE_MAX_STRING,
    MAX_APPROX_CHARS_PER_TOKEN,
    MAX_COMPLETION_TOKENS,
    MAX_LLM_CACHE_TTL_SECONDS,
    MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MAX_TRACE_MAX_DICT_ITEMS,
    MAX_TRACE_MAX_LIST_ITEMS,
    MAX_TRACE_MAX_STRING,
    MIN_APPROX_CHARS_PER_TOKEN,
    MIN_COMPLETION_TOKENS,
    MIN_LLM_CACHE_TTL_SECONDS,
    MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MIN_TRACE_MAX_DICT_ITEMS,
    MIN_TRACE_MAX_LIST_ITEMS,
    MIN_TRACE_MAX_STRING,
)
