"""Installed plugins: who installed which version where, what they confirmed and what the plugin brought."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

SCOPE_WORKSPACE, SCOPE_PLATFORM = "workspace", "platform"
PLUGIN_SCOPES = (SCOPE_WORKSPACE, SCOPE_PLATFORM)
STATUS_ACTIVE, STATUS_DISABLED = "active", "disabled"
PLATFORM_SCOPE_KEY = "platform"


class PluginInstall(WorkspaceBound, Base):
    __workspace_column__ = "workspace_id"
    __tablename__ = "plugin_installs"
    __table_args__ = (UniqueConstraint("plugin_key", "scope_key", name="uq_plugin_installs_plugin_scope"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plugin_key = Column(String(80), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    version = Column(String(40), nullable=False)
    publisher = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="")
    scope = Column(String(20), nullable=False)
    scope_key = Column(String(36), nullable=False)  # the Workspace id, or "platform"
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default=STATUS_ACTIVE)
    source_json = Column(JSON, nullable=False, default=dict)
    package_digest = Column(String(80), nullable=False)
    consent_digest = Column(String(80), nullable=False)
    manifest_json = Column(JSON, nullable=False, default=dict)
    permissions_json = Column(JSON, nullable=False, default=dict)
    contributions_json = Column(JSON, nullable=False, default=list)
    findings_json = Column(JSON, nullable=False, default=list)
    settings_json = Column(JSON, nullable=True)  # plain settings; secrets live in the secret store
    installed_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    installed_at = Column(DateTime, nullable=False, default=utc_now)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class PluginUiFile(WorkspaceBound, Base):
    """One file of a plugin's UI bundle, kept at install and served under ``/plugin-ui``."""
    __workspace_column__ = None
    __workspace_owners__ = {"install_id": "plugin_installs"}

    __tablename__ = "plugin_ui_files"
    __table_args__ = (UniqueConstraint("install_id", "path", name="uq_plugin_ui_files_install_path"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    install_id = Column(String(36), ForeignKey("plugin_installs.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(500), nullable=False)
    content_type = Column(String(120), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    content = Column(LargeBinary, nullable=False)


__all__ = ["PluginUiFile", "PLATFORM_SCOPE_KEY", "PLUGIN_SCOPES", "SCOPE_PLATFORM", "SCOPE_WORKSPACE", "STATUS_ACTIVE",
           "STATUS_DISABLED", "PluginInstall"]
