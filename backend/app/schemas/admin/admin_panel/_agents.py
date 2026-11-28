from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.services.agent_reply_contract_schema import ReplyContractError, normalize_reply_contract

from ...core.workspace_ref import OptionalWorkspaceId

# The panel write body uses snake_case fields (``tool_surface``, ``reply_contract``); the read payload is camelCase.
ToolSurfaceValue = Literal["governed", "none"]


def _reject_null_reply_contract(data: Any) -> Any:
    if isinstance(data, dict) and "reply_contract" in data and data["reply_contract"] is None:
        # Omit the key to keep the stored format; {"kind": "text"} turns the check off. null is never text.
        raise PydanticCustomError("agent_reply_contract_invalid", "The reply format cannot be null")
    return data


def _valid_reply_contract(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return normalize_reply_contract(value)
    except ReplyContractError as exc:
        raise PydanticCustomError("agent_reply_contract_invalid", str(exc)) from None


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    goal: str = ""
    group_id: str | None = None
    runtime_target_id: str | None = None
    agent_type: str = "diagnosis"
    thinking_level: str = "light"
    branch_prefix: str = "octryx"
    require_self_review: bool = False
    tool_surface: ToolSurfaceValue = "governed"
    # Omitted means free text; validated and normalized here and again by the service.
    reply_contract: dict[str, Any] | None = None
    system_prompt: str = ""
    output_prompt: str = ""
    is_active: bool = True

    _reply_contract_null = model_validator(mode="before")(_reject_null_reply_contract)
    _reply_contract_value = field_validator("reply_contract")(_valid_reply_contract)


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    goal: str | None = None
    group_id: str | None = None
    runtime_target_id: str | None = None
    agent_type: str | None = None
    thinking_level: str | None = None
    branch_prefix: str | None = None
    require_self_review: bool | None = None
    # Omitted keeps the stored value; an explicit null is refused like any unknown value.
    tool_surface: ToolSurfaceValue = None
    # Omitted keeps the stored format; {"kind": "text"} turns the check off; null is refused.
    reply_contract: dict[str, Any] | None = None
    system_prompt: str | None = None
    output_prompt: str | None = None
    is_active: bool | None = None

    _reply_contract_null = model_validator(mode="before")(_reject_null_reply_contract)
    _reply_contract_value = field_validator("reply_contract")(_valid_reply_contract)


class AgentStepCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    step_type: str = "analysis"
    instructions: str = ""
    success_criteria: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    step_config: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class AgentStepUpdateRequest(BaseModel):
    name: str | None = None
    step_type: str | None = None
    instructions: str | None = None
    success_criteria: str | None = None
    allowed_tools: list[str] | None = None
    step_config: dict[str, Any] | None = None
    is_enabled: bool | None = None


class AgentGroupCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    slug: str | None = None
    description: str = ""
    category: str = "general"
    project_id: OptionalWorkspaceId = None
    position: int = Field(default=100, ge=0, le=10000)
    is_active: bool = True


class AgentGroupUpdateRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    category: str | None = None
    project_id: OptionalWorkspaceId = None
    position: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None
