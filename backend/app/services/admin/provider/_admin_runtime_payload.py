"""Payload builders shared by admin runtime service handlers."""

from __future__ import annotations

from typing import Any

RUNTIME_SETTINGS_RESPONSE_KEYS = (
    "agent_default_model",
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
    "security_analyzer_chain",
    "artifact_store_backend",
    "artifact_store_bucket",
    "artifact_store_prefix",
    "artifact_store_s3_region",
    "artifact_store_s3_endpoint_url",
)


# Shown, never written here: the default model comes from the platform order, the sync defaults are built in.
_READ_ONLY_RUNTIME_SETTINGS = frozenset({
    "agent_default_model",
    "session_workspace_sync_default_excluded_dirs",
    "session_workspace_sync_default_excluded_globs",
})
WRITABLE_RUNTIME_SETTINGS = frozenset(RUNTIME_SETTINGS_RESPONSE_KEYS) - _READ_ONLY_RUNTIME_SETTINGS | {
    "max_output_tokens_default",
}


def unknown_runtime_settings(payload: dict[str, Any], *, extra: frozenset[str] = frozenset()) -> list[str]:
    return sorted(set(payload) - WRITABLE_RUNTIME_SETTINGS - extra)


def build_runtime_settings_payload(
    *,
    max_output_tokens_default: int | None,
    runtime_settings: dict[str, Any],
    security_analyzer_options: list[str],
    cost_limit_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "max_output_tokens_default": max_output_tokens_default,
    }
    for key in RUNTIME_SETTINGS_RESPONSE_KEYS:
        payload[key] = runtime_settings[key]
    payload["security_analyzer_options"] = security_analyzer_options
    payload["cost_limit_scope"] = cost_limit_scope or {
        "scope": "global",
        "project_id": "",
        "session_source": "global",
        "request_source": "global",
        "project_session_cost_limit_usd": None,
        "project_request_cost_limit_usd": None,
    }
    return payload
