"""Payload builders shared by admin runtime service handlers."""

from __future__ import annotations

from typing import Any

RUNTIME_SETTINGS_RESPONSE_KEYS = (
    "agent_default_model",
    "default_completion_tokens",
    "extended_completion_tokens",
    "approx_chars_per_token",
    "trace_max_string",
    "trace_max_list_items",
    "trace_max_dict_items",
    "saved_script_max_output_chars",
    "runtime_request_timeout_seconds",
    "runtime_fallback_mode",
    "auth_oidc_only",
    "agent_session_cost_limit_usd",
    "agent_request_cost_limit_usd",
    "llm_cache_ttl_seconds",
    "llm_cache_tools_ttl_seconds",
    "llm_tool_planner_trace_call_enabled",
    "llm_tool_planner_max_tokens",
    "llm_tool_planner_timeout_seconds",
    "execution_runtime_provider",
    "execution_runtime_docker_image",
    "execution_runtime_docker_network_mode",
    "execution_runtime_allow_host_fallback",
    "execution_runtime_sandbox_mode",
    "execution_runtime_docker_memory_mb",
    "execution_runtime_docker_pids_limit",
    "session_workspace_base_dir",
    "session_workspace_max_age_hours",
    "session_workspace_storage_backend",
    "session_workspace_storage_bucket",
    "session_workspace_storage_prefix",
    "session_workspace_sync_excluded_dirs",
    "session_workspace_sync_default_excluded_dirs",
    "session_workspace_sync_excluded_globs",
    "session_workspace_sync_default_excluded_globs",
    "session_workspace_sync_max_file_size_bytes",
    "session_workspace_sync_max_file_count",
    "office_template_library",
    "llm_security_analyzer_timeout_seconds",
    "llm_security_analyzer_review_threshold",
    "llm_security_analyzer_deny_threshold",
    "stuck_loop_tool_repeat_threshold",
    "stuck_loop_blocked_tool_threshold",
    "stuck_loop_repeated_jira_threshold",
    "stuck_loop_no_tool_duplicate_threshold",
    "stuck_loop_summary_repeat_threshold",
    "stuck_loop_no_tool_similarity_threshold",
    "elastic_iteration_enabled",
    "elastic_iteration_max_bonus",
    "elastic_iteration_unique_tool_threshold",
    "security_analyzer_chain",
    "artifact_store_backend",
    "artifact_store_bucket",
    "artifact_store_prefix",
    "artifact_store_s3_region",
    "artifact_store_s3_endpoint_url",
)


def build_runtime_settings_payload(
    *,
    max_output_tokens_default: int | None,
    runtime_settings: dict[str, Any],
    security_analyzer_options: list[str],
    context_budget_profiles: list[dict[str, Any]],
    cost_limit_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "max_output_tokens_default": max_output_tokens_default,
    }
    for key in RUNTIME_SETTINGS_RESPONSE_KEYS:
        payload[key] = runtime_settings[key]
    payload["security_analyzer_options"] = security_analyzer_options
    payload["context_budget_profiles"] = context_budget_profiles
    payload["cost_limit_scope"] = cost_limit_scope or {
        "scope": "global",
        "project_id": "",
        "session_source": "global",
        "request_source": "global",
        "project_session_cost_limit_usd": None,
        "project_request_cost_limit_usd": None,
    }
    return payload
