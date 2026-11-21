from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...runtime_limits import MAX_COMPLETION_TOKENS, MAX_PROVIDER_CONTEXT_BUDGET, MIN_COMPLETION_TOKENS


class ProviderCreateRequest(BaseModel):
    driver: str = Field(min_length=1)
    name: str | None = None
    provider_family: str | None = None
    runtime_kind: str | None = None
    display_name: str = ""
    profile_name: str | None = None
    endpoint_url: str | None = None
    binary_path: str | None = None
    auth_mode: str | None = None
    api_key: str | None = None
    config_json: dict[str, Any] | None = None
    capabilities_json: dict[str, Any] | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_region: str | None = None
    aws_role_arn: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_cloud_project: str | None = None
    bootstrap_role: str | None = None
    is_global: bool = True


class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    provider_family: str | None = None
    driver: str | None = None
    runtime_kind: str | None = None
    display_name: str | None = None
    profile_name: str | None = None
    endpoint_url: str | None = None
    binary_path: str | None = None
    auth_mode: str | None = None
    api_key: str | None = None
    config_json: dict[str, Any] | None = None
    capabilities_json: dict[str, Any] | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_region: str | None = None
    aws_role_arn: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_cloud_project: str | None = None
    bootstrap_role: str | None = None
    is_active: bool | None = None


class ProviderModelCreateRequest(BaseModel):
    model_id: str = Field(min_length=1)
    display_name: str = ""
    context_length: int | None = None
    planner_context_budget: int | None = Field(default=None, ge=1000, le=MAX_PROVIDER_CONTEXT_BUDGET)
    max_tokens_per_request: int | None = Field(default=None, ge=MIN_COMPLETION_TOKENS, le=MAX_COMPLETION_TOKENS)
    pricing_input: float | None = Field(default=None, ge=0)
    pricing_output: float | None = Field(default=None, ge=0)
    supports_tools: bool = True
    supports_vision: bool = False


class ProviderModelUpdateRequest(BaseModel):
    is_active: bool | None = None
    display_name: str | None = None
    planner_context_budget: int | None = Field(default=None, ge=1000, le=MAX_PROVIDER_CONTEXT_BUDGET)
    max_tokens_per_request: int | None = Field(default=None, ge=MIN_COMPLETION_TOKENS, le=MAX_COMPLETION_TOKENS)
    pricing_input: float | None = Field(default=None, ge=0)
    pricing_output: float | None = Field(default=None, ge=0)
    # Prompt-cache rate pair, USD per million tokens; null clears (not priced), 0 is a price.
    pricing_cache_read: float | None = Field(default=None, ge=0)
    pricing_cache_write: float | None = Field(default=None, ge=0)
    supports_tools: bool | None = None
    supports_vision: bool | None = None


class ProviderModelPullRequest(BaseModel):
    model_id: str = Field(min_length=1)


class LocalBootstrapHealthRequest(BaseModel):
    endpoint_url: str | None = None
    auto_start: bool = True


class LocalBootstrapSetupRequest(BaseModel):
    endpoint_url: str | None = None
    model_id: str = Field(default="gemma4", min_length=1)
    display_name: str = "Local Gemma 4 Anchor"
    pull_model: bool = True
    make_primary: bool = True
    auto_start: bool = True


__all__ = [
    "LocalBootstrapHealthRequest",
    "LocalBootstrapSetupRequest",
    "ProviderCreateRequest",
    "ProviderModelCreateRequest",
    "ProviderModelPullRequest",
    "ProviderModelUpdateRequest",
    "ProviderUpdateRequest",
]
