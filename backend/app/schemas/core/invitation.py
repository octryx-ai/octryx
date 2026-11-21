from pydantic import BaseModel, Field

from .workspace_ref import OptionalWorkspaceId


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    team_id: str | None = Field(default=None, max_length=36)
    project_id: OptionalWorkspaceId = Field(default=None, max_length=36)
    role: str = Field(default="member", min_length=1, max_length=30)
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 14)


class InvitationAcceptRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=255)
    display_name: str | None = Field(default=None, max_length=200)


class InvitationResponse(BaseModel):
    id: str
    email: str
    team_id: str | None
    project_id: str | None
    role: str
    invite_url: str
    delivery_method: str
    expires_at: str
    accepted_at: str | None = None
