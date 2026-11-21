"""Persisted, non-secret MCP server registry models."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now

MCP_OWNER_PLATFORM = "platform"
MCP_OWNER_WORKSPACE = "workspace"
MCP_SECRET_TARGET_ENV = "env"
MCP_SECRET_TARGET_HEADER = "header"


def uuid_pk() -> str:
    return str(uuid.uuid4())


def canonical_name_default(context) -> str:
    return str(context.get_current_parameters().get("name") or "").strip().casefold()


class McpServerRegistration(Base):
    """Authoritative non-secret connection metadata for one MCP server."""

    __tablename__ = "mcp_server_registrations"
    __table_args__ = (
        CheckConstraint(
            "(owner_scope = 'platform' AND workspace_id IS NULL) OR "
            "(owner_scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_mcp_server_registrations_owner",
        ),
        CheckConstraint(
            "transport IN ('stdio', 'sse', 'streamable-http')",
            name="ck_mcp_server_registrations_transport",
        ),
        Index("ix_mcp_server_registrations_workspace_active", "workspace_id", "is_active"),
        Index("ix_mcp_server_registrations_owner_active", "owner_scope", "is_active"),
        Index(
            "uq_mcp_server_registrations_platform_name",
            "canonical_name",
            unique=True,
            sqlite_where=text("owner_scope = 'platform'"),
            postgresql_where=text("owner_scope = 'platform'"),
        ),
        Index(
            "uq_mcp_server_registrations_workspace_name",
            "workspace_id",
            "canonical_name",
            unique=True,
            sqlite_where=text("owner_scope = 'workspace'"),
            postgresql_where=text("owner_scope = 'workspace'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(160), nullable=False, index=True)
    canonical_name = Column(String(160), nullable=False, index=True, default=canonical_name_default)
    owner_scope = Column(String(20), nullable=False)
    workspace_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    transport = Column(String(40), nullable=False)
    command = Column(String(220), nullable=False, default="")
    args_json = Column(JSON, nullable=False, default=list)
    url = Column(Text, nullable=True)
    description = Column(Text, nullable=False, default="")
    catalog_slug = Column(String(100), nullable=True, index=True)
    settings_json = Column(JSON, nullable=False, default=dict)
    auto_start = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=False, index=True)
    revision = Column(Integer, nullable=False, default=1)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    workspace = relationship("Project")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
    secret_bindings = relationship(
        "McpServerSecretBinding",
        back_populates="server",
        cascade="all, delete-orphan",
        order_by="McpServerSecretBinding.field_name.asc()",
    )


class McpServerSecretBinding(Base):
    """Opaque Secret Reference placement for a trusted MCP catalog field."""

    __tablename__ = "mcp_server_secret_bindings"
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('env', 'header')",
            name="ck_mcp_server_secret_bindings_target_kind",
        ),
        Index("ix_mcp_server_secret_bindings_server_field", "server_id", "field_name", unique=True),
        Index("ix_mcp_server_secret_bindings_secret", "secret_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    server_id = Column(
        String(36),
        ForeignKey("mcp_server_registrations.id", ondelete="CASCADE"),
        nullable=False,
    )
    secret_id = Column(String(36), ForeignKey("stored_secrets.id"), nullable=False)
    field_name = Column(String(200), nullable=False)
    target_kind = Column(String(20), nullable=False)
    target_name = Column(String(200), nullable=False)
    target_aliases_json = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    server = relationship("McpServerRegistration", back_populates="secret_bindings")
    secret = relationship("StoredSecret")


__all__ = [
    "MCP_OWNER_PLATFORM",
    "MCP_OWNER_WORKSPACE",
    "MCP_SECRET_TARGET_ENV",
    "MCP_SECRET_TARGET_HEADER",
    "McpServerRegistration",
    "McpServerSecretBinding",
]
