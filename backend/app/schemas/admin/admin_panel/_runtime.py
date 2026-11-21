from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...core.workspace_ref import OptionalWorkspaceId

# Sampling override (``accepts_temperature``): "catalog" (default), "accepts" or "rejects" ("never send").
# The temperature value itself is set on the model catalog row (``LLMModel.temperature``).
TemperatureSupport = Literal["catalog", "accepts", "rejects"]


class RuntimeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    make_primary: bool = False
    use_case_tags: list[str] | None = None
    # Governed model capabilities (W22b), validated against the admin capability catalog.
    capability_tags: list[str] | None = None
    # Sampling override (``accepts_temperature``): "catalog" (default), "accepts" or "rejects".
    temperature_support: TemperatureSupport | None = None


class RuntimeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_case_tags: list[str] | None = None
    capability_tags: list[str] | None = None
    temperature_support: TemperatureSupport | None = None
    is_active: bool | None = None
    model_id: str | None = None


class ChannelCreateRequest(BaseModel):
    plugin_id: str = Field(min_length=1)
    name: str = ""
    project_id: OptionalWorkspaceId = None
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelUpdateRequest(BaseModel):
    name: str | None = None
    project_id: OptionalWorkspaceId = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
