from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..core.workspace_ref import OptionalWorkspaceId


class AgentChainStepRequest(BaseModel):
    id: str | None = None
    name: str | None = None
    agent_type: str = Field(min_length=1, max_length=64)
    thinking_level: str | None = Field(default=None, max_length=32)
    execution_mode: Literal["sequential", "parallel"] = "sequential"
    parallel_group: str | None = Field(default=None, max_length=64)
    input_mapping: dict[str, Any] | str | None = None
    output_mapping: dict[str, Any] | None = None

    @field_validator("agent_type", "thinking_level", "parallel_group", mode="before")
    @classmethod
    def _strip_optional_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class AgentChainTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    project_id: OptionalWorkspaceId = None
    is_active: bool = True
    steps: list[AgentChainStepRequest] = Field(min_length=1)


class AgentChainTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    project_id: OptionalWorkspaceId = None
    is_active: bool | None = None
    steps: list[AgentChainStepRequest] | None = None


class AgentChainRunCreateRequest(BaseModel):
    input_payload: dict[str, Any] = Field(default_factory=dict)
    parent_session_id: str | None = None
