"""Extensible work roles: functions with tool sets, roles and per-Workspace assignments."""
from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

GLOBAL_SCOPE = "global"
ANY_PROVIDER = "*"
SUBJECT_KINDS = ("user", "group", "sso_group", "sso_role")
DELIVERY_ALL, DELIVERY_SELECTED = "all", "selected"


def _uuid() -> str:
    return str(uuid.uuid4())


class WorkRoleFunction(WorkspaceBound, Base):
    __tablename__ = "work_role_functions"
    __table_args__ = (
        UniqueConstraint("scope_key", "key", name="uq_work_role_functions_key"),
        CheckConstraint("version >= 1 AND tools_version >= 1", name="ck_work_role_functions_version"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    key = Column(String(40), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="")
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    scope_key = Column(String(36), nullable=False, default=GLOBAL_SCOPE)
    built_in = Column(Boolean, nullable=False, default=False)
    tools_json = Column(JSON, nullable=False, default=list)
    tools_version = Column(Integer, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class WorkRole(WorkspaceBound, Base):
    __tablename__ = "work_roles"
    __table_args__ = (
        UniqueConstraint("scope_key", "key", name="uq_work_roles_key"),
        CheckConstraint("delivery_connections IN ('all','selected')", name="ck_work_roles_delivery"),
        CheckConstraint("version >= 1", name="ck_work_roles_version"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    key = Column(String(40), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="")
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    scope_key = Column(String(36), nullable=False, default=GLOBAL_SCOPE)
    built_in = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    # Delivery is granted per connection: "all" lets the role write through every connection the
    # Workspace allows; "selected" only through ``connection_ids_json`` (named connection ids).
    delivery_connections = Column(String(10), nullable=False, default=DELIVERY_ALL)
    connection_ids_json = Column(JSON, nullable=False, default=list)
    # Chat writes without per-call confirmation: an explicit, audited opt-in, off by default.
    trusted = Column(Boolean, nullable=False, default=False)
    trusted_changed_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    trusted_changed_at = Column(DateTime, nullable=True)
    # Phase shell rules on top of the Workspace's Command safety: {"allow": [glob], "deny": [glob]}.
    command_policy_json = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class WorkRoleFunctionLink(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"role_id": "work_roles"}
    __tablename__ = "work_role_function_links"

    role_id = Column(String(36), ForeignKey("work_roles.id", ondelete="CASCADE"), primary_key=True)
    function_id = Column(String(36), ForeignKey("work_role_functions.id", ondelete="CASCADE"), primary_key=True,
                         index=True)


class WorkRoleAssignment(WorkspaceBound, Base):
    __tablename__ = "work_role_assignments"
    __table_args__ = (
        CheckConstraint("subject_kind IN ('user','group','sso_group','sso_role')", name="ck_work_role_assign_kind"),
        CheckConstraint(
            "(subject_kind = 'user' AND user_id IS NOT NULL AND group_id IS NULL AND claim_value IS NULL) OR "
            "(subject_kind = 'group' AND group_id IS NOT NULL AND user_id IS NULL AND claim_value IS NULL) OR "
            "(subject_kind IN ('sso_group','sso_role') AND claim_value IS NOT NULL AND user_id IS NULL "
            "AND group_id IS NULL)", name="ck_work_role_assign_subject"),
        CheckConstraint("version >= 1", name="ck_work_role_assign_version"),
        UniqueConstraint("project_id", "role_id", "subject_kind", "subject_key", "provider_key",
                         name="uq_work_role_assignment"),
        Index("ix_work_role_assign_project_active", "project_id", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(String(36), ForeignKey("work_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_kind = Column(String(12), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(String(36), ForeignKey("identity_groups.id", ondelete="CASCADE"), nullable=True)
    claim_value = Column(String(255), nullable=True)
    provider_id = Column(String(36), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=True)
    # Uniqueness keys: the subject's id or claim value, and the provider (``*`` = any provider).
    subject_key = Column(String(255), nullable=False)
    provider_key = Column(String(36), nullable=False, default=ANY_PROVIDER)
    is_active = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class WorkspaceWorkRoleSettings(WorkspaceBound, Base):
    __tablename__ = "workspace_work_role_settings"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_workspace_work_role_settings_version"),)

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    # "Role-based tools": OFF by default; nothing changes for a Workspace until an admin turns it on.
    role_based_tools = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=1)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=True)


class WorkRoleAuditEvent(WorkspaceBound, Base):
    """Every admin edit of functions, roles, assignments, the switch and the SSO mapping. ``project_id`` has no foreign
    key: the history outlives a deleted Workspace or role."""

    __tablename__ = "work_role_audit_events"
    __table_args__ = (Index("ix_work_role_audit_project_created", "project_id", "created_at"),
                      Index("ix_work_role_audit_target", "target_type", "target_id"))

    id = Column(String(36), primary_key=True, default=_uuid)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(60), nullable=False)
    project_id = Column(String(36), nullable=True)
    target_type = Column(String(20), nullable=False)
    target_id = Column(String(36), nullable=False)
    target_label = Column(String(200), nullable=False, default="")
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
