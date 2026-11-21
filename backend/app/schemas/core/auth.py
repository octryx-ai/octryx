from datetime import datetime

from pydantic import BaseModel, Field

from .workspace_ref import OptionalWorkspaceId


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    display_name: str | None
    roles: list[str]
    is_active: bool
    created_at: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    display_name: str | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None


class UserMeUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    project_id: OptionalWorkspaceId = None
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class APIKeyResponse(BaseModel):
    id: str
    user_id: str
    project_id: str | None
    name: str
    scopes: list[str]
    key_prefix: str
    last_used_at: str | None
    expires_at: str | None
    revoked_at: str | None
    created_at: str | None


class APIKeyCreateResponse(APIKeyResponse):
    api_key: str
