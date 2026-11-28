"""Loading raw runtime-related setting values from SystemConfig."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.system_config.constants import (
    AGENT_APPROX_CHARS_PER_TOKEN_KEY,
    AGENT_AUTH_LOGIN_MODE_KEY,
    AGENT_EXECUTION_RUNTIME_ALLOW_HOST_FALLBACK_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_IMAGE_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_NETWORK_MODE_KEY,
    AGENT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT_KEY,
    AGENT_EXECUTION_RUNTIME_PROVIDER_KEY,
    AGENT_EXECUTION_RUNTIME_SANDBOX_MODE_KEY,
    AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY,
    AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY,
    AGENT_OFFICE_TEMPLATE_LIBRARY_KEY,
    AGENT_REQUEST_COST_LIMIT_USD_KEY,
    AGENT_RUNTIME_FALLBACK_MODE_KEY,
    AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS_KEY,
    AGENT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES_KEY,
    AGENT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS_KEY,
    AGENT_SAVED_SCRIPT_MAX_OUTPUT_CHARS_KEY,
    AGENT_SECURITY_ANALYZER_CHAIN_KEY,
    AGENT_SESSION_COST_LIMIT_USD_KEY,
    AGENT_SESSION_WORKSPACE_BASE_DIR_KEY,
    AGENT_SESSION_WORKSPACE_MAX_AGE_HOURS_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
    AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY,
    AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY,
    AGENT_TRACE_MAX_DICT_ITEMS_KEY,
    AGENT_TRACE_MAX_LIST_ITEMS_KEY,
    AGENT_TRACE_MAX_STRING_KEY,
    ARTIFACT_STORE_BACKEND_KEY,
    ARTIFACT_STORE_BUCKET_KEY,
    ARTIFACT_STORE_PREFIX_KEY,
    ARTIFACT_STORE_S3_ENDPOINT_URL_KEY,
    ARTIFACT_STORE_S3_REGION_KEY,
)
from app.services.system_config.values import get_system_config_value


async def _task_model_id(db: AsyncSession, task: str) -> str:
    from ..model_selection.task_roles import task_model_id

    return await task_model_id(db, task)


async def load_agent_runtime_setting_values(db: AsyncSession) -> dict[str, str | None]:
    return {
        "approx_chars_per_token": await get_system_config_value(db, AGENT_APPROX_CHARS_PER_TOKEN_KEY),
        "trace_max_string": await get_system_config_value(db, AGENT_TRACE_MAX_STRING_KEY),
        "trace_max_list_items": await get_system_config_value(db, AGENT_TRACE_MAX_LIST_ITEMS_KEY),
        "trace_max_dict_items": await get_system_config_value(db, AGENT_TRACE_MAX_DICT_ITEMS_KEY),
        "saved_script_max_output_chars": await get_system_config_value(db, AGENT_SAVED_SCRIPT_MAX_OUTPUT_CHARS_KEY),
        "runtime_request_timeout_seconds": await get_system_config_value(db, AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS_KEY),
        "runtime_unreachable_retry_max_retries": await get_system_config_value(
            db,
            AGENT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES_KEY,
        ),
        "auth_oidc_only": await get_system_config_value(db, AGENT_AUTH_LOGIN_MODE_KEY),
        "runtime_unreachable_retry_pause_seconds": await get_system_config_value(
            db,
            AGENT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS_KEY,
        ),
        "runtime_fallback_mode": await get_system_config_value(db, AGENT_RUNTIME_FALLBACK_MODE_KEY),
        "agent_session_cost_limit_usd": await get_system_config_value(db, AGENT_SESSION_COST_LIMIT_USD_KEY),
        "agent_request_cost_limit_usd": await get_system_config_value(db, AGENT_REQUEST_COST_LIMIT_USD_KEY),
        # The review model is the ``security_review`` Task model (empty: the platform default).
        "security_review_model": await _task_model_id(db, "security_review"),
        "execution_runtime_provider": await get_system_config_value(db, AGENT_EXECUTION_RUNTIME_PROVIDER_KEY),
        "execution_runtime_docker_image": await get_system_config_value(db, AGENT_EXECUTION_RUNTIME_DOCKER_IMAGE_KEY),
        "execution_runtime_docker_network_mode": await get_system_config_value(
            db,
            AGENT_EXECUTION_RUNTIME_DOCKER_NETWORK_MODE_KEY,
        ),
        "execution_runtime_allow_host_fallback": await get_system_config_value(
            db,
            AGENT_EXECUTION_RUNTIME_ALLOW_HOST_FALLBACK_KEY,
        ),
        "execution_runtime_sandbox_mode": await get_system_config_value(db, AGENT_EXECUTION_RUNTIME_SANDBOX_MODE_KEY),
        "execution_runtime_docker_memory_mb": await get_system_config_value(
            db,
            AGENT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB_KEY,
        ),
        "execution_runtime_docker_pids_limit": await get_system_config_value(
            db,
            AGENT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT_KEY,
        ),
        "session_workspace_base_dir": await get_system_config_value(db, AGENT_SESSION_WORKSPACE_BASE_DIR_KEY),
        "session_workspace_max_age_hours": await get_system_config_value(db, AGENT_SESSION_WORKSPACE_MAX_AGE_HOURS_KEY),
        "session_workspace_storage_backend": await get_system_config_value(
            db,
            AGENT_SESSION_WORKSPACE_STORAGE_BACKEND_KEY,
        ),
        "session_workspace_storage_bucket": await get_system_config_value(
            db,
            AGENT_SESSION_WORKSPACE_STORAGE_BUCKET_KEY,
        ),
        "session_workspace_storage_prefix": await get_system_config_value(
            db,
            AGENT_SESSION_WORKSPACE_STORAGE_PREFIX_KEY,
        ),
        "session_workspace_sync_excluded_dirs": await get_system_config_value(
            db,
            AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_DIRS_KEY,
        ),
        "session_workspace_sync_excluded_globs": await get_system_config_value(
            db,
            AGENT_SESSION_WORKSPACE_SYNC_EXCLUDED_GLOBS_KEY,
        ),
        "session_workspace_sync_max_file_size_bytes": await get_system_config_value(
            db,
            AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_SIZE_BYTES_KEY,
        ),
        "session_workspace_sync_max_file_count": await get_system_config_value(
            db,
            AGENT_SESSION_WORKSPACE_SYNC_MAX_FILE_COUNT_KEY,
        ),
        "office_template_library": await get_system_config_value(db, AGENT_OFFICE_TEMPLATE_LIBRARY_KEY),
        "security_analyzer_chain": await get_system_config_value(db, AGENT_SECURITY_ANALYZER_CHAIN_KEY),
        "llm_security_analyzer_timeout_seconds": await get_system_config_value(
            db,
            AGENT_LLM_SECURITY_ANALYZER_TIMEOUT_SECONDS_KEY,
        ),
        "llm_security_analyzer_review_threshold": await get_system_config_value(
            db,
            AGENT_LLM_SECURITY_ANALYZER_REVIEW_THRESHOLD_KEY,
        ),
        "llm_security_analyzer_deny_threshold": await get_system_config_value(
            db,
            AGENT_LLM_SECURITY_ANALYZER_DENY_THRESHOLD_KEY,
        ),
        "artifact_store_backend": await get_system_config_value(db, ARTIFACT_STORE_BACKEND_KEY),
        "artifact_store_bucket": await get_system_config_value(db, ARTIFACT_STORE_BUCKET_KEY),
        "artifact_store_prefix": await get_system_config_value(db, ARTIFACT_STORE_PREFIX_KEY),
        "artifact_store_s3_region": await get_system_config_value(db, ARTIFACT_STORE_S3_REGION_KEY),
        "artifact_store_s3_endpoint_url": await get_system_config_value(db, ARTIFACT_STORE_S3_ENDPOINT_URL_KEY),
    }
