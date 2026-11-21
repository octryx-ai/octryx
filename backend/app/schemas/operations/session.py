from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.workspace_ref import OptionalWorkspaceId


class SessionCreate(BaseModel):
    project_id: OptionalWorkspaceId = None
    agent_type: str | None = None


class MessageCreate(BaseModel):
    content: str
    # Explicit workflow selection (published definition key); empty means
    # the Workspace's workflow proposal (services/workflow_routing/explicit_selection.py).
    workflow_key: str = ""
    # Structured answer to a workflow clarification question, e.g.
    # {"private_dependencies": "standalone_parent"}; closed values only.
    workflow_decisions: dict[str, str] = Field(default_factory=dict)
    # The turn's runtime, thinking level and agent, chosen like on /chat/api. Omitted
    # (None) means the session's, the agent's or the Workspace's default; an unknown
    # runtime is refused (``runtime_target_invalid``), an unknown thinking level runs
    # as ``light``.
    runtime_target_id: str | None = Field(default=None, max_length=100)
    thinking_level: str | None = Field(default=None, max_length=20)
    agent_id: str | None = Field(default=None, max_length=100)

    @field_validator("workflow_decisions")
    @classmethod
    def _closed_workflow_decisions(cls, value: dict[str, str]) -> dict[str, str]:
        from app.services.workflow_contracts.decisions import validate_workflow_decisions

        return validate_workflow_decisions(value)


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str | None
    tool_calls: list | None = None
    tool_results: list | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class SessionResponse(BaseModel):
    id: str
    user_id: str
    project_id: str | None
    agent_type: str
    status: str
    started_at: str
    ended_at: str | None = None
    message_count: int = 0
    access_role: str = "owner"

    model_config = ConfigDict(from_attributes=True)


class SessionCollaboratorCreate(BaseModel):
    user_id: str
    role: str = "observer"


class SessionCollaboratorResponse(BaseModel):
    session_id: str
    user_id: str
    role: str
    invited_by: str
    joined_at: str | None = None


class SessionHandoverCreate(BaseModel):
    to_user_id: str
    reason: str | None = None
    context_summary: str | None = None


class SessionAccessGrant(BaseModel):
    user_id: str
    access_scope: str = "read"
    expires_at: str | None = None
    metadata: dict | None = None


class SessionAccessGrantResponse(BaseModel):
    session_id: str
    user_id: str | None = None
    access_scope: str
    granted_by: str | None = None
    expires_at: str | None = None


class SessionHandoverRespond(BaseModel):
    action: str


class SessionHandoverResponse(BaseModel):
    id: str
    session_id: str
    from_user_id: str
    to_user_id: str
    reason: str | None = None
    context_summary: str | None = None
    status: str
    created_at: str | None = None
    resolved_at: str | None = None


class SessionStreamTokenResponse(BaseModel):
    session_id: str
    token: str
