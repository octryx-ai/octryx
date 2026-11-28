"""A stored batch of an octryx-claude session's transcript (behind a Workspace switch)."""

from __future__ import annotations

import secrets

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def transcript_chunk_pk() -> str:
    return f"stc_{secrets.token_hex(10)}"


class SessionTranscriptChunk(WorkspaceBound, Base):
    __tablename__ = "session_transcript_chunks"
    __table_args__ = (
        UniqueConstraint("project_id", "claude_session_id", "stream", "first_line",
                         name="uq_session_transcript_chunks_batch"),
        Index("ix_session_transcript_chunks_session_stream", "session_id", "stream", "first_line"),
        Index("ix_session_transcript_chunks_project_created", "project_id", "created_at"),
    )

    id = Column(String(40), primary_key=True, default=transcript_chunk_pk)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    claude_session_id = Column(String(80), nullable=False)
    stream = Column(String(80), nullable=False)
    first_line = Column(Integer, nullable=False)
    last_line = Column(Integer, nullable=False)
    line_count = Column(Integer, nullable=False)
    byte_size = Column(Integer, nullable=False)
    workflow_run_id = Column(String(36), nullable=True, index=True)
    device_job_id = Column(String(40), nullable=True, index=True)
    storage_backend = Column(String(20), nullable=False)
    storage_location = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


__all__ = ["SessionTranscriptChunk", "transcript_chunk_pk"]
