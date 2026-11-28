from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...runtime_limits import (
    MAX_APPROX_CHARS_PER_TOKEN,
    MAX_COMPLETION_TOKENS,
    MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MAX_TRACE_MAX_DICT_ITEMS,
    MAX_TRACE_MAX_LIST_ITEMS,
    MAX_TRACE_MAX_STRING,
    MIN_APPROX_CHARS_PER_TOKEN,
    MIN_COMPLETION_TOKENS,
    MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    MIN_TRACE_MAX_DICT_ITEMS,
    MIN_TRACE_MAX_LIST_ITEMS,
    MIN_TRACE_MAX_STRING,
)


class CopilotDevicePollRequest(BaseModel):
    flow_id: str = Field(min_length=1)


class RuntimeDirectionRequest(BaseModel):
    direction: Literal["up", "down"] = "up"


class ReorderRequest(BaseModel):
    order: list[str] = Field(default_factory=list)


class RuntimeSettingsUpdateRequest(BaseModel):
    # Undeclared keys are kept (``extra="allow"``) so the service refuses unknown ones by name
    # (``unknown_runtime_settings``). Use ``to_update_payload()`` to build the service payload.
    model_config = ConfigDict(extra="allow")

    max_output_tokens_default: int | None = Field(default=None, ge=MIN_COMPLETION_TOKENS, le=MAX_COMPLETION_TOKENS)
    execution_runtime_provider: Literal["host", "docker"] | None = None
    execution_runtime_docker_image: str | None = None
    execution_runtime_docker_network_mode: Literal["none", "bridge", "host"] | None = None
    auth_oidc_only: bool | None = None
    execution_runtime_allow_host_fallback: bool | None = None
    execution_runtime_sandbox_mode: Literal["compat", "hard"] | None = None
    execution_runtime_docker_memory_mb: int | None = Field(default=None, ge=128, le=8192)
    execution_runtime_docker_pids_limit: int | None = Field(default=None, ge=32, le=4096)
    session_workspace_base_dir: str | None = None
    session_workspace_max_age_hours: int | None = Field(default=None, ge=0, le=24 * 365)
    session_workspace_storage_backend: Literal["disabled", "filesystem", "s3"] | None = None
    session_workspace_storage_bucket: str | None = None
    session_workspace_storage_prefix: str | None = None
    artifact_store_backend: Literal["filesystem", "s3", "gcs"] | None = None
    artifact_store_bucket: str | None = None
    artifact_store_prefix: str | None = None
    artifact_store_s3_region: str | None = None
    artifact_store_s3_endpoint_url: str | None = None
    session_workspace_sync_excluded_dirs: str | None = None
    session_workspace_sync_excluded_globs: str | None = None
    session_workspace_sync_max_file_size_bytes: int | None = Field(default=None, ge=0, le=1024 * 1024 * 1024)
    session_workspace_sync_max_file_count: int | None = Field(default=None, ge=0, le=100000)
    office_template_library: list[dict[str, Any]] | None = None
    llm_security_analyzer_timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    llm_security_analyzer_review_threshold: int | None = Field(default=None, ge=0, le=100)
    llm_security_analyzer_deny_threshold: int | None = Field(default=None, ge=0, le=100)
    security_analyzer_chain: list[str] | None = None
    approx_chars_per_token: int | None = Field(
        default=None,
        ge=MIN_APPROX_CHARS_PER_TOKEN,
        le=MAX_APPROX_CHARS_PER_TOKEN,
    )
    trace_max_string: int | None = Field(default=None, ge=MIN_TRACE_MAX_STRING, le=MAX_TRACE_MAX_STRING)
    trace_max_list_items: int | None = Field(
        default=None,
        ge=MIN_TRACE_MAX_LIST_ITEMS,
        le=MAX_TRACE_MAX_LIST_ITEMS,
    )
    trace_max_dict_items: int | None = Field(
        default=None,
        ge=MIN_TRACE_MAX_DICT_ITEMS,
        le=MAX_TRACE_MAX_DICT_ITEMS,
    )
    saved_script_max_output_chars: int | None = Field(
        default=None,
        ge=MIN_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
        le=MAX_SAVED_SCRIPT_MAX_OUTPUT_CHARS,
    )
    runtime_request_timeout_seconds: int | None = Field(
        default=None,
        ge=MIN_RUNTIME_REQUEST_TIMEOUT_SECONDS,
        le=MAX_RUNTIME_REQUEST_TIMEOUT_SECONDS,
    )
    # Deliberately ``str | None`` and not a ``Literal``: the closed enum is owned
    # by the service writer (``_admin_runtime_fallback_policy``), which answers an
    # unknown value with a stable 400 naming the setting and the admitted modes.
    # A transport-level ``Literal`` would pre-empt that with a 422 and a pydantic
    # message instead. ``""`` stays a legal value — it is the explicit "clear the
    # governed setting and fall back to the per-driver default" write, and
    # ``model_dump(exclude_none=True)`` keeps it while dropping an absent field.
    runtime_fallback_mode: str | None = None
    agent_session_cost_limit_usd: float | None = Field(default=None, ge=0.0, le=1_000_000.0)
    agent_request_cost_limit_usd: float | None = Field(default=None, ge=0.0, le=1_000_000.0)
    # Workspace scope only: the caps whose override is removed so the platform value applies again.
    inherit_cost_limits: list[Literal["agent_session_cost_limit_usd", "agent_request_cost_limit_usd"]] | None = None

    def to_update_payload(self) -> dict[str, Any]:
        return {**self.model_dump(exclude_none=True), **(self.model_extra or {})}


