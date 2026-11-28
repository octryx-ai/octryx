"""Traceability links from design artifacts into delivery execution."""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class DesignArtifactTraceLink(WorkspaceBound, Base):
    __tablename__ = "design_artifact_trace_links"
    __table_args__ = (
        Index("ix_design_trace_project_artifact", "project_id", "artifact_id"),
        Index("ix_design_trace_project_target", "project_id", "target_type"),
        Index("ix_design_trace_artifact_target", "artifact_id", "target_type"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    artifact_id = Column(String(36), ForeignKey("design_artifacts.id"), nullable=False, index=True)
    target_type = Column(String(40), nullable=False, index=True)
    target_id = Column(String(36), nullable=True, index=True)
    title = Column(String(240), nullable=False)
    status = Column(String(40), nullable=False, default="active", index=True)
    url = Column(String(2000), nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")
    artifact = relationship("DesignArtifact", back_populates="trace_links")
    created_by = relationship("User")
