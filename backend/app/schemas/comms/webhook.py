from pydantic import BaseModel, ConfigDict, Field, field_serializer

from ..core.workspace_ref import WorkspaceId


class WebhookCreate(BaseModel):
    """A webhook starts an Action (no agent mode); same validation as the admin panel."""

    project_id: WorkspaceId
    name: str
    description: str | None = None
    source_type: str = "generic"
    task_id: str | None = None
    alert_filter: str | None = None
    group_window_minutes: int | None = Field(default=None, ge=0, le=1440)
    rate_limit_per_hour: int | None = Field(default=None, ge=1, le=1000)
    accept_untimestamped: bool = False
    agent_type: str | None = None  # optional; validated by the service like an Action's mode


def _mask_secret(secret: str) -> str:
    if not secret or len(secret) < 12:
        return "***"
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


class WebhookResponse(BaseModel):
    id: str
    project_id: str
    owner_id: str
    name: str
    description: str | None = None
    source_type: str
    task_id: str | None = None
    alert_filter: str = "critical_warning"
    group_window_minutes: int = 30
    rate_limit_per_hour: int = 20
    accept_untimestamped: bool = False
    # Never expose the raw secret in API responses — mask it.
    # The actual secret is stored encrypted and used only for webhook validation.
    secret: str
    is_active: bool
    created_at: str

    @field_serializer("secret")
    def serialize_secret(self, secret: str) -> str:
        return _mask_secret(secret)

    model_config = ConfigDict(from_attributes=True)


class WebhookSecretResponse(WebhookResponse):
    """The answer to a create or a rotate: the only time the raw secret is returned, so the caller can put it into the
    sender (with only the masked value every delivery would be
    refused). Lists and reads keep :class:`WebhookResponse`, masked."""

    @field_serializer("secret")
    def serialize_secret(self, secret: str) -> str:
        return secret


class WebhookEventResponse(BaseModel):
    id: str
    webhook_id: str
    session_id: str | None = None
    status: str
    parsed_message: str | None = None
    error: str | None = None
    received_at: str
    processed_at: str | None = None

    model_config = ConfigDict(from_attributes=True)
