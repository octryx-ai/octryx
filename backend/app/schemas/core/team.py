from pydantic import BaseModel, Field

from .workspace_ref import WorkspaceId


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=500)


class TeamMemberAddRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    role: str = Field(default="member", min_length=1, max_length=30)


class TeamProjectGrantRequest(BaseModel):
    project_id: WorkspaceId = Field(min_length=1, max_length=36)
    role: str = Field(default="member", min_length=1, max_length=30)


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str | None
    avatar_url: str | None
    created_by: str
    created_at: str
    my_role: str | None = None
    member_count: int = 0
    project_count: int = 0
