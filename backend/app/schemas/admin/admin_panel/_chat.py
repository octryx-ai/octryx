from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ....models.project.knowledge_answer_feedback import (
    MAX_FEEDBACK_TEXT_CHARS,
    AspectVerdict,
    FeedbackAspect,
    FeedbackRating,
)


class ChatExecutionTarget(BaseModel):
    """Where a chat message runs: the Server (today's behaviour) or one of the sender's devices."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["server", "device"] = "server"
    device_id: str = Field(default="", max_length=40)
    folder: str = Field(default="", max_length=500)
    profile: str = Field(default="", max_length=20)
    # The model the device job runs with; empty: the device's default.
    model: str = Field(default="", max_length=200)
    # Claude Code's permission mode and effort for this turn; empty: the device's default.
    permission_mode: Literal["", "default", "acceptEdits", "plan", "bypassPermissions"] = ""
    effort: Literal["", "low", "medium", "high", "xhigh", "max"] = ""


class ChatSendRequest(BaseModel):
    prompt: str = Field(min_length=1)
    session_id: str = ""
    project_id: str = ""
    runtime_target_id: str = ""
    agent_id: str = ""
    workflow_key: str = ""
    # Structured answer to a workflow clarification question, e.g.
    # {"private_dependencies": "standalone_parent"}; closed values only.
    workflow_decisions: dict[str, str] = Field(default_factory=dict)
    thinking_level: str = "light"
    idempotency_key: str | None = None
    execution_target: ChatExecutionTarget | None = None

    @field_validator("workflow_decisions")
    @classmethod
    def _closed_workflow_decisions(cls, value: dict[str, str]) -> dict[str, str]:
        from app.services.workflow_contracts.decisions import validate_workflow_decisions

        return validate_workflow_decisions(value)


class ChatContinueRequest(BaseModel):
    prompt: str = ""
    runtime_target_id: str | None = None
    thinking_level: str | None = None


class ChatMessageRerunRequest(BaseModel):
    prompt: str = Field(min_length=1)


class ChatRenameRequest(BaseModel):
    title: str = ""


class MessageFeedbackRequest(BaseModel):
    """Answer feedback: good or bad (required), what was good, what was not good, and marked aspects.

    Closed values only; an unknown field, rating, aspect or verdict is refused (422), never coerced.
    The service re-validates and applies the Memory lobe's text guard (``feedback_contract``).
    """

    model_config = ConfigDict(extra="forbid")

    rating: FeedbackRating
    liked: str | None = Field(default=None, max_length=MAX_FEEDBACK_TEXT_CHARS)
    disliked: str | None = Field(default=None, max_length=MAX_FEEDBACK_TEXT_CHARS)
    aspects: dict[FeedbackAspect, AspectVerdict] = Field(default_factory=dict)
