"""Agent runtime settings assembly from DB-backed system config."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.office.template import merge_office_template_libraries
from app.services.session.workspace_storage import (
    normalize_workspace_storage_backend,
    normalize_workspace_storage_prefix,
)
from app.services.session.workspace_sync import (
    DEFAULT_SYNC_EXCLUDED_DIRS,
    DEFAULT_SYNC_EXCLUDED_GLOBS,
    DEFAULT_SYNC_MAX_FILE_COUNT,
)
from app.services.system_config.constants import (
    DEFAULT_AGENT_REQUEST_COST_LIMIT_USD,
    DEFAULT_AGENT_SESSION_COST_LIMIT_USD,
    DEFAULT_APPROX_CHARS_PER_TOKEN,
    DEFAULT_ELASTIC_ITERATION_ENABLED,
    DEFAULT_ELASTIC_ITERATION_MAX_BONUS,
    DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD,
    DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE,
    DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB,
    DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT,
    DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE,
    DEFAULT_EXECUTION_RUNTIME_PROVIDER,
    DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE,
    DEFAULT_EXTENDED_COMPLETION_TOKENS,
    DEFAULT_LLM_CACHE_TOOLS_TTL_SECONDS,
    DEFAULT_LLM_CACHE_TTL_SECONDS,
    DEFAULT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD,
    DEFAULT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD,
    DEFAULT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS,
    DEFAULT_LLM_TOOL_PLANNER_MAX_TOKENS,
    DEFAULT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS,
    DEFAULT_LLM_TOOL_PLANNER_TRACE_CALL_ENABLED,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES,
    DEFAULT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS,
    DEFAULT_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    DEFAULT_SECURITY_ANALYZER_CHAIN,
    DEFAULT_SESSION_WORKSPACE_MAX_AGE_HOURS,
    DEFAULT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD,
    DEFAULT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD,
    DEFAULT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD,
    DEFAULT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD,
    DEFAULT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD,
    DEFAULT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD,
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
    MIN_LLM_TOOL_PLANNER_MAX_TOKENS,
    MIN_LLM_TOOL_PLANNER_TIMEOUT_SECONDS,
    MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MIN_TRACE_MAX_DICT_ITEMS,
    MIN_TRACE_MAX_LIST_ITEMS,
    MIN_TRACE_MAX_STRING,
)
from app.services.system_config.runtime_values import load_agent_runtime_setting_values
from app.services.system_config.values import bounded_float, bounded_int, get_agent_default_model


async def get_agent_runtime_settings(db: AsyncSession) -> dict[str, Any]:
    raw_values = await load_agent_runtime_setting_values(db)
    default_completion_tokens = raw_values["default_completion_tokens"]
    extended_completion_tokens = raw_values["extended_completion_tokens"]
    approx_chars_per_token = raw_values["approx_chars_per_token"]
    trace_max_string = raw_values["trace_max_string"]
    trace_max_list_items = raw_values["trace_max_list_items"]
    trace_max_dict_items = raw_values["trace_max_dict_items"]
    saved_script_max_output_chars = raw_values["saved_script_max_output_chars"]
    runtime_request_timeout_seconds = raw_values["runtime_request_timeout_seconds"]
    auth_oidc_only = raw_values["auth_oidc_only"]
    runtime_unreachable_retry_max_retries = raw_values["runtime_unreachable_retry_max_retries"]
    runtime_unreachable_retry_pause_seconds = raw_values["runtime_unreachable_retry_pause_seconds"]
    runtime_fallback_mode = raw_values["runtime_fallback_mode"]
    agent_session_cost_limit_usd = raw_values["agent_session_cost_limit_usd"]
    agent_request_cost_limit_usd = raw_values["agent_request_cost_limit_usd"]
    llm_cache_ttl_seconds = raw_values["llm_cache_ttl_seconds"]
    llm_cache_tools_ttl_seconds = raw_values["llm_cache_tools_ttl_seconds"]
    llm_tool_planner_trace_call_enabled = raw_values["llm_tool_planner_trace_call_enabled"]
    llm_tool_planner_max_tokens = raw_values["llm_tool_planner_max_tokens"]
    llm_tool_planner_timeout_seconds = raw_values["llm_tool_planner_timeout_seconds"]
    security_review_model = raw_values["security_review_model"]
    execution_runtime_provider = raw_values["execution_runtime_provider"]
    execution_runtime_docker_image = raw_values["execution_runtime_docker_image"]
    execution_runtime_docker_network_mode = raw_values["execution_runtime_docker_network_mode"]
    execution_runtime_allow_host_fallback = raw_values["execution_runtime_allow_host_fallback"]
    execution_runtime_sandbox_mode = raw_values["execution_runtime_sandbox_mode"]
    execution_runtime_docker_memory_mb = raw_values["execution_runtime_docker_memory_mb"]
    execution_runtime_docker_pids_limit = raw_values["execution_runtime_docker_pids_limit"]
    session_workspace_base_dir = raw_values["session_workspace_base_dir"]
    session_workspace_max_age_hours = raw_values["session_workspace_max_age_hours"]
    session_workspace_storage_backend = raw_values["session_workspace_storage_backend"]
    session_workspace_storage_bucket = raw_values["session_workspace_storage_bucket"]
    session_workspace_storage_prefix = raw_values["session_workspace_storage_prefix"]
    session_workspace_sync_excluded_dirs = raw_values["session_workspace_sync_excluded_dirs"]
    session_workspace_sync_excluded_globs = raw_values["session_workspace_sync_excluded_globs"]
    session_workspace_sync_max_file_size_bytes = raw_values["session_workspace_sync_max_file_size_bytes"]
    session_workspace_sync_max_file_count = raw_values["session_workspace_sync_max_file_count"]
    office_template_library = raw_values["office_template_library"]
    security_analyzer_chain = raw_values["security_analyzer_chain"]
    llm_security_analyzer_timeout_seconds = raw_values["llm_security_analyzer_timeout_seconds"]
    llm_security_analyzer_review_threshold = raw_values["llm_security_analyzer_review_threshold"]
    llm_security_analyzer_deny_threshold = raw_values["llm_security_analyzer_deny_threshold"]
    stuck_loop_tool_repeat_threshold = raw_values["stuck_loop_tool_repeat_threshold"]
    stuck_loop_blocked_tool_threshold = raw_values["stuck_loop_blocked_tool_threshold"]
    stuck_loop_repeated_jira_threshold = raw_values["stuck_loop_repeated_jira_threshold"]
    stuck_loop_no_tool_duplicate_threshold = raw_values["stuck_loop_no_tool_duplicate_threshold"]
    stuck_loop_summary_repeat_threshold = raw_values["stuck_loop_summary_repeat_threshold"]
    stuck_loop_no_tool_similarity_threshold = raw_values["stuck_loop_no_tool_similarity_threshold"]
    elastic_iteration_enabled = raw_values["elastic_iteration_enabled"]
    elastic_iteration_max_bonus = raw_values["elastic_iteration_max_bonus"]
    elastic_iteration_unique_tool_threshold = raw_values["elastic_iteration_unique_tool_threshold"]
    artifact_store_backend = raw_values["artifact_store_backend"]
    artifact_store_bucket = raw_values["artifact_store_bucket"]
    artifact_store_prefix = raw_values["artifact_store_prefix"]
    artifact_store_s3_region = raw_values["artifact_store_s3_region"]
    artifact_store_s3_endpoint_url = raw_values["artifact_store_s3_endpoint_url"]
    try:
        parsed_security_analyzer_chain = json.loads(security_analyzer_chain) if security_analyzer_chain else None
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed_security_analyzer_chain = None
    try:
        parsed_office_template_library = json.loads(office_template_library) if office_template_library else None
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed_office_template_library = None
    if not isinstance(parsed_security_analyzer_chain, list):
        parsed_security_analyzer_chain = list(DEFAULT_SECURITY_ANALYZER_CHAIN)
    parsed_office_template_library = merge_office_template_libraries(parsed_office_template_library)
    sandbox_mode = (
        (execution_runtime_sandbox_mode or DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE).strip().lower()
        if (execution_runtime_sandbox_mode or DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE).strip().lower()
        in {"compat", "hard"}
        else DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE
    )
    allow_host_fallback = str(execution_runtime_allow_host_fallback or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if sandbox_mode == "hard":
        allow_host_fallback = False

    return {
        "agent_default_model": await get_agent_default_model(db),
        "default_completion_tokens": bounded_int(
            default_completion_tokens,
            default=DEFAULT_MAX_COMPLETION_TOKENS,
            minimum=MIN_COMPLETION_TOKENS,
            maximum=MAX_COMPLETION_TOKENS,
        ),
        "extended_completion_tokens": bounded_int(
            extended_completion_tokens,
            default=DEFAULT_EXTENDED_COMPLETION_TOKENS,
            minimum=MIN_COMPLETION_TOKENS,
            maximum=MAX_COMPLETION_TOKENS,
        ),
        "approx_chars_per_token": bounded_int(
            approx_chars_per_token,
            default=DEFAULT_APPROX_CHARS_PER_TOKEN,
            minimum=MIN_APPROX_CHARS_PER_TOKEN,
            maximum=MAX_APPROX_CHARS_PER_TOKEN,
        ),
        "trace_max_string": bounded_int(
            trace_max_string,
            default=DEFAULT_TRACE_MAX_STRING,
            minimum=MIN_TRACE_MAX_STRING,
            maximum=MAX_TRACE_MAX_STRING,
        ),
        "trace_max_list_items": bounded_int(
            trace_max_list_items,
            default=DEFAULT_TRACE_MAX_LIST_ITEMS,
            minimum=MIN_TRACE_MAX_LIST_ITEMS,
            maximum=MAX_TRACE_MAX_LIST_ITEMS,
        ),
        "trace_max_dict_items": bounded_int(
            trace_max_dict_items,
            default=DEFAULT_TRACE_MAX_DICT_ITEMS,
            minimum=MIN_TRACE_MAX_DICT_ITEMS,
            maximum=MAX_TRACE_MAX_DICT_ITEMS,
        ),
        "saved_script_max_output_chars": bounded_int(
            saved_script_max_output_chars,
            default=DEFAULT_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
            minimum=MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
            maximum=MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
        ),
        "runtime_request_timeout_seconds": bounded_int(
            runtime_request_timeout_seconds,
            default=DEFAULT_RUNTIME_REQUEST_TIMEOUT_SECONDS,
            minimum=MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
            maximum=MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
        ),
        "auth_oidc_only": str(auth_oidc_only or "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        "runtime_unreachable_retry_max_retries": bounded_int(
            runtime_unreachable_retry_max_retries,
            default=DEFAULT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES,
            minimum=0,
            maximum=10,
        ),
        "runtime_unreachable_retry_pause_seconds": bounded_int(
            runtime_unreachable_retry_pause_seconds,
            default=DEFAULT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS,
            minimum=0,
            maximum=60,
        ),
        # Passed through raw (trimmed only). Empty means "not governed": the
        # engine then applies the per-driver default, and a stored value outside
        # the closed mode set must stay visible as invalid instead of being
        # normalized into the permissive mode here.
        "runtime_fallback_mode": str(runtime_fallback_mode or "").strip(),
        "agent_session_cost_limit_usd": bounded_float(
            agent_session_cost_limit_usd,
            default=DEFAULT_AGENT_SESSION_COST_LIMIT_USD,
            minimum=0.0,
            maximum=1000000.0,
        ),
        "agent_request_cost_limit_usd": bounded_float(
            agent_request_cost_limit_usd,
            default=DEFAULT_AGENT_REQUEST_COST_LIMIT_USD,
            minimum=0.0,
            maximum=1000000.0,
        ),
        "llm_cache_ttl_seconds": bounded_int(
            llm_cache_ttl_seconds,
            default=DEFAULT_LLM_CACHE_TTL_SECONDS,
            minimum=MIN_LLM_CACHE_TTL_SECONDS,
            maximum=MAX_LLM_CACHE_TTL_SECONDS,
        ),
        "llm_cache_tools_ttl_seconds": bounded_int(
            llm_cache_tools_ttl_seconds,
            default=DEFAULT_LLM_CACHE_TOOLS_TTL_SECONDS,
            minimum=MIN_LLM_CACHE_TTL_SECONDS,
            maximum=MAX_LLM_CACHE_TTL_SECONDS,
        ),
        "llm_tool_planner_trace_call_enabled": str(
            llm_tool_planner_trace_call_enabled or DEFAULT_LLM_TOOL_PLANNER_TRACE_CALL_ENABLED
        )
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        "llm_tool_planner_max_tokens": bounded_int(
            llm_tool_planner_max_tokens,
            default=DEFAULT_LLM_TOOL_PLANNER_MAX_TOKENS,
            minimum=MIN_LLM_TOOL_PLANNER_MAX_TOKENS,
            maximum=MAX_COMPLETION_TOKENS,
        ),
        "llm_tool_planner_timeout_seconds": bounded_int(
            llm_tool_planner_timeout_seconds,
            default=DEFAULT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS,
            minimum=MIN_LLM_TOOL_PLANNER_TIMEOUT_SECONDS,
            maximum=MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
        ),
        # Live, not runtime routing: the llm_risk security analyzer's model
        # (services/security_analyzer/llm_risk).
        "security_review_model": security_review_model or "",
        "execution_runtime_provider": (execution_runtime_provider or DEFAULT_EXECUTION_RUNTIME_PROVIDER)
        .strip()
        .lower(),
        "execution_runtime_docker_image": execution_runtime_docker_image or DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE,
        "execution_runtime_docker_network_mode": (
            execution_runtime_docker_network_mode or DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE
        )
        .strip()
        .lower(),
        "execution_runtime_allow_host_fallback": allow_host_fallback,
        "execution_runtime_sandbox_mode": sandbox_mode,
        "execution_runtime_docker_memory_mb": bounded_int(
            execution_runtime_docker_memory_mb,
            default=DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB,
            minimum=128,
            maximum=8192,
        ),
        "execution_runtime_docker_pids_limit": bounded_int(
            execution_runtime_docker_pids_limit,
            default=DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT,
            minimum=32,
            maximum=4096,
        ),
        "session_workspace_base_dir": str(session_workspace_base_dir or "").strip(),
        "session_workspace_max_age_hours": bounded_int(
            session_workspace_max_age_hours,
            default=DEFAULT_SESSION_WORKSPACE_MAX_AGE_HOURS,
            minimum=0,
            maximum=24 * 365,
        ),
        "session_workspace_storage_backend": normalize_workspace_storage_backend(session_workspace_storage_backend),
        "session_workspace_storage_bucket": str(session_workspace_storage_bucket or "").strip(),
        "session_workspace_storage_prefix": normalize_workspace_storage_prefix(session_workspace_storage_prefix),
        "session_workspace_sync_excluded_dirs": str(session_workspace_sync_excluded_dirs or "").strip(),
        "session_workspace_sync_default_excluded_dirs": sorted(DEFAULT_SYNC_EXCLUDED_DIRS),
        "session_workspace_sync_excluded_globs": str(session_workspace_sync_excluded_globs or "").strip(),
        "session_workspace_sync_default_excluded_globs": sorted(DEFAULT_SYNC_EXCLUDED_GLOBS),
        "session_workspace_sync_max_file_size_bytes": bounded_int(
            session_workspace_sync_max_file_size_bytes,
            default=0,
            minimum=0,
            maximum=1024 * 1024 * 1024,
        ),
        "session_workspace_sync_max_file_count": bounded_int(
            session_workspace_sync_max_file_count,
            default=DEFAULT_SYNC_MAX_FILE_COUNT,
            minimum=0,
            maximum=100000,
        ),
        "office_template_library": parsed_office_template_library,
        "llm_security_analyzer_timeout_seconds": bounded_int(
            llm_security_analyzer_timeout_seconds,
            default=DEFAULT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS,
            minimum=1,
            maximum=60,
        ),
        "llm_security_analyzer_review_threshold": bounded_int(
            llm_security_analyzer_review_threshold,
            default=DEFAULT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD,
            minimum=0,
            maximum=100,
        ),
        "llm_security_analyzer_deny_threshold": bounded_int(
            llm_security_analyzer_deny_threshold,
            default=DEFAULT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD,
            minimum=0,
            maximum=100,
        ),
        "stuck_loop_tool_repeat_threshold": bounded_int(
            stuck_loop_tool_repeat_threshold,
            default=DEFAULT_STUCK_LOOP_TOOL_REPEAT_THRESHOLD,
            minimum=3,
            maximum=12,
        ),
        "stuck_loop_blocked_tool_threshold": bounded_int(
            stuck_loop_blocked_tool_threshold,
            default=DEFAULT_STUCK_LOOP_BLOCKED_TOOL_THRESHOLD,
            minimum=1,
            maximum=6,
        ),
        "stuck_loop_repeated_jira_threshold": bounded_int(
            stuck_loop_repeated_jira_threshold,
            default=DEFAULT_STUCK_LOOP_REPEATED_JIRA_THRESHOLD,
            minimum=2,
            maximum=10,
        ),
        "stuck_loop_no_tool_duplicate_threshold": bounded_int(
            stuck_loop_no_tool_duplicate_threshold,
            default=DEFAULT_STUCK_LOOP_NO_TOOL_DUPLICATE_THRESHOLD,
            minimum=2,
            maximum=6,
        ),
        "stuck_loop_summary_repeat_threshold": bounded_int(
            stuck_loop_summary_repeat_threshold,
            default=DEFAULT_STUCK_LOOP_SUMMARY_REPEAT_THRESHOLD,
            minimum=1,
            maximum=4,
        ),
        "stuck_loop_no_tool_similarity_threshold": max(
            0.5,
            min(
                float(stuck_loop_no_tool_similarity_threshold or DEFAULT_STUCK_LOOP_NO_TOOL_SIMILARITY_THRESHOLD),
                0.99,
            ),
        ),
        "elastic_iteration_enabled": str(elastic_iteration_enabled or str(DEFAULT_ELASTIC_ITERATION_ENABLED))
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        "elastic_iteration_max_bonus": bounded_int(
            elastic_iteration_max_bonus,
            default=DEFAULT_ELASTIC_ITERATION_MAX_BONUS,
            minimum=0,
            maximum=12,
        ),
        "elastic_iteration_unique_tool_threshold": bounded_int(
            elastic_iteration_unique_tool_threshold,
            default=DEFAULT_ELASTIC_ITERATION_UNIQUE_TOOL_THRESHOLD,
            minimum=1,
            maximum=6,
        ),
        "security_analyzer_chain": [str(item).strip() for item in parsed_security_analyzer_chain if str(item).strip()]
        or list(DEFAULT_SECURITY_ANALYZER_CHAIN),
        "artifact_store_backend": str(artifact_store_backend or "filesystem").strip().lower(),
        "artifact_store_bucket": str(artifact_store_bucket or "").strip(),
        "artifact_store_prefix": str(artifact_store_prefix or "").strip().strip("/"),
        "artifact_store_s3_region": str(artifact_store_s3_region or "").strip(),
        "artifact_store_s3_endpoint_url": str(artifact_store_s3_endpoint_url or "").strip(),
    }
