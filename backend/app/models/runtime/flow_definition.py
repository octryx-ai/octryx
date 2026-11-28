from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class FlowDefinition(WorkspaceBound, Base):
    __tablename__ = "flow_definitions"
    __table_args__ = (
        UniqueConstraint("key", "project_id", name="uq_flow_definitions_key_project"),
        Index("ix_flow_definitions_project_status", "project_id", "status"),
        Index("ix_flow_definitions_active", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(180), nullable=False, index=True)
    name = Column(String(220), nullable=False)
    description = Column(Text, default="")
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    status = Column(String(40), nullable=False, default="draft", index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    current_version_id = Column(String(36), nullable=True, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)

    project = relationship("Project")
    creator = relationship("User")
    versions = relationship(
        "FlowDefinitionVersion",
        back_populates="flow",
        cascade="all, delete-orphan",
        order_by="FlowDefinitionVersion.version.desc()",
        foreign_keys="FlowDefinitionVersion.flow_id",
    )


class FlowDefinitionVersion(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"flow_id": "flow_definitions"}
    __tablename__ = "flow_definition_versions"
    __table_args__ = (
        UniqueConstraint("flow_id", "version", name="uq_flow_definition_versions_flow_version"),
        Index("ix_flow_definition_versions_flow_status", "flow_id", "status"),
        Index("ix_flow_definition_versions_published", "status", "published_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    flow_id = Column(String(36), ForeignKey("flow_definitions.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(40), nullable=False, default="draft", index=True)
    definition_json = Column(JSON, nullable=False, default=dict)
    validation_report = Column(JSON, nullable=False, default=dict)
    publish_metadata = Column(JSON, nullable=False, default=dict)
    runtime_settings = Column(JSON, nullable=False, default=dict)
    policy_bindings = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    published_at = Column(DateTime, nullable=True, index=True)

    flow = relationship("FlowDefinition", back_populates="versions", foreign_keys=[flow_id])
    creator = relationship("User", foreign_keys=[created_by])
    publisher = relationship("User", foreign_keys=[published_by])
