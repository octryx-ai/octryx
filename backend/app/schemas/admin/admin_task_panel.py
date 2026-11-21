from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ...runtime_limits import MAX_AGENT_TIMEOUT_SECONDS, MAX_CONCURRENT_AGENTS, MAX_FIX_ATTEMPTS
from ..core.workspace_ref import OptionalWorkspaceId

DispatchBinding = Literal["task_definition", "agent_definition", "workflow_run"]


class TaskCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    project_id: OptionalWorkspaceId = None
    task_type: str = "agent_run"
    agent_type: str = "diagnosis"
    schedule: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    max_concurrent_agents: int = Field(default=3, ge=1, le=MAX_CONCURRENT_AGENTS)
    is_active: bool = True
    default_runtime_selector: dict[str, Any] | None = None
    # How the Action runs, always authored on create; the service validates the full bound state.
    dispatch_binding: DispatchBinding


class TaskUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    task_type: str | None = None
    agent_type: str | None = None
    schedule: str | None = None
    config: dict[str, Any] | None = None
    max_concurrent_agents: int | None = Field(default=None, ge=1, le=MAX_CONCURRENT_AGENTS)
    is_active: bool | None = None
    default_runtime_selector: dict[str, Any] | None = None
    # Omitted keeps the stored binding.
    dispatch_binding: DispatchBinding | None = None


class TaskStepCreateRequest(BaseModel):
    name: str = "Step"
    step_type: str = "analysis"
    connector: str | None = None
    connector_action: str | None = None
    connector_params: dict[str, Any] = Field(default_factory=dict)
    instructions: str = ""
    runtime_selector: dict[str, Any] = Field(default_factory=dict)
    context_fields: list[Any] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    spawn_strategy: str = "per_item"
    spawn_count: int | None = None
    max_fix_attempts: int = Field(default=2, ge=0, le=MAX_FIX_ATTEMPTS)
    condition_expr: str | None = None
    condition_true_step: str | None = None
    condition_false_step: str | None = None
    agent_timeout_seconds: int = Field(default=300, ge=1, le=MAX_AGENT_TIMEOUT_SECONDS)
    is_enabled: bool = True


class TaskStepUpdateRequest(BaseModel):
    name: str | None = None
    step_type: str | None = None
    connector: str | None = None
    connector_action: str | None = None
    connector_params: dict[str, Any] | None = None
    instructions: str | None = None
    runtime_selector: dict[str, Any] | None = None
    context_fields: list[Any] | None = None
    allowed_tools: list[str] | None = None
    spawn_strategy: str | None = None
    spawn_count: int | None = None
    max_fix_attempts: int | None = Field(default=None, ge=0, le=MAX_FIX_ATTEMPTS)
    condition_expr: str | None = None
    condition_true_step: str | None = None
    condition_false_step: str | None = None
    agent_timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_AGENT_TIMEOUT_SECONDS)
    is_enabled: bool | None = None
    position: int | None = None


class TaskDependencyUpsertRequest(BaseModel):
    depends_on_task_id: str = Field(min_length=1)
    condition: str = Field(default="success", pattern="^(success|failure|always)$")


class SchedulerCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    cron_expression: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    is_active: bool = True


class SchedulerUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    task_id: str | None = None
    is_active: bool | None = None


class SchedulerPreviewRequest(BaseModel):
    # Transport bound only; the 100-character column limit is reported as a typed preview error.
    cron_expression: str = Field(default="", max_length=1000)
    count: int = Field(default=5, ge=1, le=10)
