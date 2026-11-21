from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.workspace_ref import OptionalWorkspaceId, WorkspaceId


class WebhookCreateRequest(BaseModel):
    """A webhook starts an Action (workflow + instructions + result destination), no agent mode."""

    name: str = Field(min_length=1)
    project_id: WorkspaceId = Field(min_length=1)
    description: str = ""
    source_type: str = "generic"
    task_id: str | None = None
    alert_filter: str | None = None
    group_window_minutes: int | None = Field(default=None, ge=0, le=1440)
    rate_limit_per_hour: int | None = Field(default=None, ge=1, le=1000)
    poll_query: str | None = Field(default=None, max_length=2000)
    accept_untimestamped: bool = False
    agent_type: str | None = None  # optional; validated by the service like an Action's mode
    result_channel_id: int | None = None
    is_active: bool = True


class WebhookUpdateRequest(BaseModel):
    name: str | None = None
    project_id: OptionalWorkspaceId = None
    description: str | None = None
    source_type: str | None = None
    task_id: str | None = None
    alert_filter: str | None = None
    group_window_minutes: int | None = Field(default=None, ge=0, le=1440)
    rate_limit_per_hour: int | None = Field(default=None, ge=1, le=1000)
    poll_query: str | None = Field(default=None, max_length=2000)
    accept_untimestamped: bool | None = None
    agent_type: str | None = None  # optional; validated by the service like an Action's mode
    is_active: bool | None = None


class WebhookTestRequest(BaseModel):
    sample: str = Field(min_length=1, max_length=64)


class OutboundWebhookCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    project_id: OptionalWorkspaceId = None
    event_types: list[str] = Field(min_length=1)
    secret: str | None = None
    is_active: bool = True


class OutboundWebhookUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    project_id: OptionalWorkspaceId = None
    event_types: list[str] | None = None
    secret: str | None = None
    rotate_secret: bool = False
    is_active: bool | None = None
