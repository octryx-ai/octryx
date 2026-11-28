import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class DesignArtifact(WorkspaceBound, Base):
    __tablename__ = "design_artifacts"
    __table_args__ = (
        Index("ix_design_artifacts_project_kind", "project_id", "artifact_kind"),
        Index("ix_design_artifacts_project_status", "project_id", "status"),
        Index("ix_design_artifacts_project_order", "project_id", "order_index", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    artifact_kind = Column(String(60), nullable=False, index=True)
    title = Column(String(240), nullable=False)
    status = Column(String(40), nullable=False, default="draft", index=True)
    summary = Column(Text, nullable=True)
    content_markdown = Column(Text, nullable=False, default="")
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    metadata_json = Column(JSON, default=dict)
    is_required = Column(Boolean, default=False, nullable=False)
    order_index = Column(Integer, default=100, nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="design_artifacts")
    owner = relationship("User")
    trace_links = relationship("DesignArtifactTraceLink", back_populates="artifact", cascade="all, delete-orphan")
