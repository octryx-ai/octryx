import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class CapabilityType(Base):
    __tablename__ = "capability_types"
    __table_args__ = (
        UniqueConstraint("kind", "key", name="uq_capability_types_kind_key"),
        Index("ix_capability_types_kind", "kind"),
        Index("ix_capability_types_active_kind", "is_active", "kind"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    kind = Column(String(50), nullable=False)
    key = Column(String(200), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    lifecycle_status = Column(String(20), nullable=False, default="active", index=True)
    contract = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    workspace_bindings = relationship("WorkspaceCapabilityBinding", back_populates="capability_type")


class WorkspaceCapabilityBinding(Base):
    __tablename__ = "workspace_capability_bindings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "binding_key", name="uq_workspace_capability_bindings_workspace_key"),
        Index("ix_workspace_capability_bindings_workspace_kind", "workspace_id", "capability_kind"),
        Index("ix_workspace_capability_bindings_workspace_default", "workspace_id", "is_default"),
        Index("ix_workspace_capability_bindings_source_entity", "source_entity_type", "source_entity_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    capability_type_id = Column(String(36), ForeignKey("capability_types.id"), nullable=False, index=True)
    capability_kind = Column(String(50), nullable=False, index=True)
    binding_key = Column(String(200), nullable=False, index=True)
    display_name = Column(String(200), nullable=False, default="")
    binding_status = Column(String(20), nullable=False, default="active", index=True)
    is_enabled = Column(Boolean, default=True, nullable=False, index=True)
    is_default = Column(Boolean, default=False, nullable=False, index=True)
    intent_scopes = Column(JSON, default=list)
    binding_config = Column(JSON, default=dict)
    policy_config = Column(JSON, default=dict)
    source_entity_type = Column(String(50), nullable=True, index=True)
    source_entity_id = Column(String(120), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    workspace = relationship("Project", back_populates="workspace_capability_bindings")
    capability_type = relationship("CapabilityType", back_populates="workspace_bindings")


class WorkspacePolicy(Base):
    __tablename__ = "workspace_policy"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_workspace_policy_workspace_id"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    default_bindings = Column(JSON, default=dict)
    routing_policy = Column(JSON, default=dict)
    delegation_policy = Column(JSON, default=dict)
    runtime_policy = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    workspace = relationship("Project", back_populates="workspace_policy", uselist=False)


__all__ = [
    "CapabilityType",
    "WorkspaceCapabilityBinding",
    "WorkspacePolicy",
]
