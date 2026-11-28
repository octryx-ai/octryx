from typing import Any

from pydantic import BaseModel, ConfigDict

from ..core.workspace_ref import OptionalWorkspaceId


class ProviderCreate(BaseModel):
    driver: str
    name: str | None = None
    provider_family: str | None = None
    runtime_kind: str | None = None
    display_name: str = ""
    profile_name: str | None = None
    endpoint_url: str | None = None
    binary_path: str | None = None
    api_key: str | None = None
    aws_region: str | None = None
    aws_role_arn: str | None = None
    auth_mode: str | None = None
    config_json: dict[str, Any] | None = None
    is_global: bool = False
    project_id: OptionalWorkspaceId = None


class ProviderResponse(BaseModel):
    id: str
    name: str
    provider_family: str | None = None
    driver: str | None = None
    runtime_kind: str | None = None
    display_name: str
    profile_name: str | None = None
    endpoint_url: str | None = None
    binary_path: str | None = None
    auth_mode: str | None = None
    is_active: bool
    is_global: bool
    project_id: str | None
    created_at: str
    model_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ModelResponse(BaseModel):
    id: str
    provider_id: str
    model_id: str
    display_name: str | None
    supports_tools: bool
    supports_vision: bool
    supports_streaming: bool
    context_length: int | None
    pricing_input: float | None
    pricing_output: float | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
