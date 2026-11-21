import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class Skill(Base):
    __tablename__ = "skills"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(100), unique=True, nullable=False)
    category = Column(String(100), nullable=False)
    source = Column(String(50), default="custom", nullable=False, index=True)
    owner_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    # Catalog identity (models/agent/skill_catalog.py). Content lives on skill_versions; the columns below are
    # identity metadata plus listing columns copied from the published version.
    kind = Column(String(20), nullable=False, default="skill")
    tags = Column(JSON, nullable=False, default=list)
    source_id = Column(String(36), ForeignKey("skill_sources.id"), nullable=True, index=True)
    upstream_path = Column(String(500), nullable=True)
    tracking_mode = Column(String(10), nullable=True)
    pinned_commit = Column(String(64), nullable=True)
    upstream_status = Column(JSON, nullable=True)
    published_version_id = Column(String(36), nullable=True)
    category_id = Column(String(36), ForeignKey("skill_categories.id"), nullable=True, index=True)
    available_platform_chat = Column(Boolean, nullable=False, default=False)
    available_octryx_claude = Column(Boolean, nullable=False, default=False)

    runs = relationship("SkillRun", back_populates="skill")


class SkillRun(Base):
    __tablename__ = "skill_runs"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    triggered_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    input_ = Column("input", JSON, default=dict)
    output = Column(JSON, nullable=True)
    status = Column(String(50), default="running")
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    skill = relationship("Skill", back_populates="runs")
    session = relationship("Session")
    triggered_by_user = relationship("User")


class SkillUsageEvent(Base):
    __tablename__ = "skill_usage_events"
    __table_args__ = (
        Index("ix_skill_usage_events_skill_created", "skill_id", "created_at"),
        Index("ix_skill_usage_events_session", "session_id"),
        Index("ix_skill_usage_events_project", "project_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    event_type = Column(String(40), nullable=False, index=True)
    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=True, index=True)
    skill_name = Column(String(100), nullable=True)
    skill_version = Column(Integer, nullable=True)
    content_level = Column(String(20), nullable=True)
    query_excerpt = Column(Text, default="")
    returned_skill_ids = Column(JSON, default=list)
    policy_status = Column(String(30), nullable=False, default="success")
    policy_reason = Column(Text, default="")
    selection_reason = Column(Text, default="")
    token_cost_estimate = Column(Integer, default=0, nullable=False)
    user_id = Column(String(36), nullable=True, index=True)
    session_id = Column(String(36), nullable=True, index=True)
    project_id = Column(String(36), nullable=True, index=True)
    agent_id = Column(String(36), nullable=True, index=True)
    request_id = Column(String(100), nullable=True, index=True)
    event_metadata = Column(JSON, default=dict)
    # Which surface used the skill (platform_chat | octryx_claude), how (search | get | model | slash),
    # and the delivered bundle digest.
    surface = Column(String(20), nullable=True, index=True)
    invocation = Column(String(20), nullable=True)
    bundle_digest = Column(String(71), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    skill = relationship("Skill")
