import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class ResearchPolicyProfile(Base):
    __tablename__ = "research_policy_profiles"
    __table_args__ = (
        UniqueConstraint("key", name="uq_research_policy_profiles_key"),
        Index("ix_research_policy_profiles_active_status", "is_active", "lifecycle_status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(120), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    lifecycle_status = Column(String(20), nullable=False, default="active", index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    versions = relationship(
        "ResearchPolicyProfileVersion",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class ResearchPolicyProfileVersion(Base):
    __tablename__ = "research_policy_profile_versions"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_research_policy_profile_versions_profile_version"),
        Index("ix_research_policy_profile_versions_profile_status", "profile_id", "status"),
        Index("ix_research_policy_profile_versions_published", "status", "published_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    profile_id = Column(String(36), ForeignKey("research_policy_profiles.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="draft", index=True)
    spec = Column(JSON, nullable=False, default=dict)
    notes = Column(Text, default="")
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    published_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    published_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    profile = relationship("ResearchPolicyProfile", back_populates="versions")
    workspace_assignments = relationship(
        "WorkspaceResearchPolicyAssignment",
        back_populates="profile_version",
        cascade="all, delete-orphan",
    )


class WorkspaceResearchPolicyAssignment(Base):
    __tablename__ = "workspace_research_policy_assignments"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_research_policy_assignments_workspace_id"),
        Index("ix_workspace_research_policy_assignments_workspace_status", "workspace_id", "assignment_status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    profile_version_id = Column(
        String(36),
        ForeignKey("research_policy_profile_versions.id"),
        nullable=False,
        index=True,
    )
    assignment_status = Column(String(20), nullable=False, default="active", index=True)
    assigned_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, default=utc_now, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    workspace = relationship("Project", back_populates="research_policy_assignment")
    profile_version = relationship(
        "ResearchPolicyProfileVersion",
        back_populates="workspace_assignments",
    )


__all__ = [
    "ResearchPolicyProfile",
    "ResearchPolicyProfileVersion",
    "WorkspaceResearchPolicyAssignment",
]
