from typing import Any

from pydantic import BaseModel, Field

from ..core.workspace_ref import OptionalWorkspaceId


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    link: str | None
    is_read: bool
    created_at: str
    read_at: str | None = None


class NotificationPreferenceUpdateRequest(BaseModel):
    """A partial update: a field left out keeps its stored value."""

    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    slack_enabled: bool | None = None
    teams_enabled: bool | None = None
    # The companion's quiet hours: {enabled, start "HH:MM", end "HH:MM", timezone}.
    quiet_hours: dict[str, Any] | None = None


class NotificationPreferenceResponse(BaseModel):
    user_id: str
    in_app_enabled: bool
    email_enabled: bool
    slack_enabled: bool
    teams_enabled: bool
    quiet_hours: dict[str, Any] | None = None


class NotificationTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    event_type: str = Field(min_length=1, max_length=100)
    channel_type: str = Field(min_length=1, max_length=30)
    project_id: OptionalWorkspaceId = None
    subject_template: str | None = None
    body_template: str = Field(min_length=1)
    is_active: bool = True


class NotificationTemplateResponse(BaseModel):
    id: str
    name: str
    event_type: str
    channel_type: str
    project_id: str | None = None
    subject_template: str | None = None
    body_template: str
    is_active: bool
    created_by: str
    created_at: str | None = None
    updated_at: str | None = None


class NotificationSubscriptionRequest(BaseModel):
    user_id: str | None = None
    project_id: OptionalWorkspaceId = None
    event_type: str = Field(min_length=1, max_length=100)
    channel_type: str = Field(min_length=1, max_length=30)
    channel_config_id: int | None = None
    target: str = Field(min_length=1, max_length=500)
    template_id: str | None = None
    is_active: bool = True


class NotificationSubscriptionResponse(BaseModel):
    id: str
    user_id: str | None = None
    project_id: str | None = None
    event_type: str
    channel_type: str
    channel_config_id: int | None = None
    target: str
    template_id: str | None = None
    is_active: bool
    created_by: str
    created_at: str | None = None
    updated_at: str | None = None


class NotificationLogResponse(BaseModel):
    id: str
    notification_id: str | None = None
    subscription_id: str | None = None
    template_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    event_type: str
    channel_type: str
    channel_config_id: int | None = None
    target: str
    subject: str | None = None
    body: str
    payload: dict = Field(default_factory=dict)
    status: str
    retry_count: int
    next_retry_at: str | None = None
    last_error: str | None = None
    sent_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
