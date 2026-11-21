"""Master-governed Flow Registry models.

FlowRegistryEntry is the top-level registry record for a flow template.
FlowRegistryVersion captures each versioned revision through the full lifecycle.

Lifecycle: draft → review → eval_passed → approved
→ published → monitored → deprecated.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class FlowRegistryEntry(Base):
    """Top-level registry record for a flow template."""

    __tablename__ = "flow_registry_entries"
    __table_args__ = (
        UniqueConstraint("key", "project_id", name="uq_flow_registry_entries_key_project"),
        Index("ix_flow_registry_entries_project_active", "project_id", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    key = Column(String(180), nullable=False, index=True)
    name = Column(String(220), nullable=False)
    description = Column(Text, default="")
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    current_version_id = Column(String(36), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)

    project = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    versions = relationship(
        "FlowRegistryVersion",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="FlowRegistryVersion.version.desc()",
        foreign_keys="FlowRegistryVersion.entry_id",
    )


class FlowRegistryVersion(Base):
    """Versioned snapshot of a flow template in the registry lifecycle."""

    __tablename__ = "flow_registry_versions"
    __table_args__ = (
        UniqueConstraint("entry_id", "version", name="uq_flow_registry_versions_entry_version"),
        Index("ix_flow_registry_versions_entry_status", "entry_id", "status"),
        Index("ix_flow_registry_versions_published", "status", "published_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    entry_id = Column(String(36), ForeignKey("flow_registry_entries.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="draft", index=True)

    # Reference to the underlying FlowDefinitionVersion
    flow_definition_version_id = Column(
        String(36), ForeignKey("flow_definition_versions.id"), nullable=True, index=True
    )

    # Evaluation gate: eval_suite_id is a plain value (no suite table references it)
    eval_suite_id = Column(String(36), nullable=True, index=True)
    eval_gate_status = Column(String(20), nullable=False, default="pending")

    # Governance metadata
    target_project_platforms = Column(JSON, nullable=False, default=list)
    dependency_policy = Column(JSON, nullable=False, default=dict)
    runtime_compatibility = Column(JSON, nullable=False, default=dict)
    publish_metadata = Column(JSON, nullable=False, default=dict)
    impact_summary = Column(JSON, nullable=False, default=dict)
    notes = Column(Text, default="")
    rolled_back_from_version = Column(Integer, nullable=True)

    # Audit
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    deprecated_by = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    published_at = Column(DateTime, nullable=True, index=True)
    deprecated_at = Column(DateTime, nullable=True)

    entry = relationship("FlowRegistryEntry", back_populates="versions", foreign_keys=[entry_id])
    flow_definition_version = relationship("FlowDefinitionVersion")
    creator = relationship("User", foreign_keys=[created_by])
    publisher = relationship("User", foreign_keys=[published_by])
    deprecator = relationship("User", foreign_keys=[deprecated_by])
