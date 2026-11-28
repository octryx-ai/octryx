"""Call agent configuration model."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base
from app.db.workspace_bound import WorkspaceBound
from app.time_utils import utc_now


def _uuid_pk():
    return str(uuid.uuid4())


_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful meeting assistant. "
    "You help with status checks, questions about projects, and decisions. "
    "You can use tools to fetch information. "
    "Answer concisely and clearly, in the language the caller uses."
)


class CallAgentConfig(WorkspaceBound, Base):
    """Configuration for CallAgent per project and optional channel."""

    __tablename__ = "call_agent_configs"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=_uuid_pk)
    name = Column(String(200), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    channel_id = Column(String(36), nullable=True, index=True)
    llm_model = Column(String(100), default="claude-sonnet-4-4")
    max_tool_calls = Column(Integer, default=5)
    system_prompt = Column(Text, nullable=False, default=_DEFAULT_SYSTEM_PROMPT)
    enabled_tools = Column(JSON, default=list)
    thinking_message = Column(
        String(500),
        default="Let me check that for you — one moment please.",
    )
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    project = relationship("Project", overlaps="project")

    def __repr__(self) -> str:
        return f"<CallAgentConfig(id={self.id}, name={self.name}, project_id={self.project_id})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "project_id": self.project_id,
            "channel_id": self.channel_id,
            "llm_model": self.llm_model,
            "max_tool_calls": self.max_tool_calls,
            "system_prompt": self.system_prompt,
            "enabled_tools": self.enabled_tools or [],
            "thinking_message": self.thinking_message,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
