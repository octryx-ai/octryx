"""Incident Response, Kill Switch, and Safe Mode models."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


SAFE_MODE_OFF = "off"
SAFE_MODE_ACTIVE = "active"

TARGET_GLOBAL = "global"
TARGET_PROJECT = "project"

ACTION_PAUSE = "pause"
ACTION_SAFE_MODE_OFF = "safe_mode_off"


class SafeModeState(WorkspaceBound, Base):
    """Current safe mode state, global or per project. When active it prevents new agent runs, flow executions and
    connector calls."""

    __tablename__ = "safe_mode_states"
    __table_args__ = (
        Index("ix_safe_mode_states_project_active", "project_id", "state"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    # NULL project_id = global safe mode; non-null = project-scoped
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    state = Column(String(20), nullable=False, default=SAFE_MODE_OFF, index=True)
    reason = Column(Text, nullable=True)
    incident_id = Column(String(100), nullable=True)  # external incident tracker ref
    activated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    activated_at = Column(DateTime, nullable=True)
    deactivated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    deactivated_at = Column(DateTime, nullable=True)
    cancel_running_work = Column(Boolean, nullable=False, default=False)
    block_new_runs = Column(Boolean, nullable=False, default=True)
    notify_users = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")


class KillSwitchLog(WorkspaceBound, Base):
    """Immutable audit log for every kill switch / pause / resume action."""

    __tablename__ = "kill_switch_logs"
    __table_args__ = (
        Index("ix_kill_switch_logs_target", "target_type", "target_id"),
        Index("ix_kill_switch_logs_created", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    action = Column(String(30), nullable=False, index=True)  # pause / resume / cancel / safe_mode_on/off
    target_type = Column(String(30), nullable=False)  # global / project / flow / task / etc.
    target_id = Column(String(36), nullable=True)  # null for global actions
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    reason = Column(Text, nullable=True)
    incident_id = Column(String(100), nullable=True)
    details = Column(JSON, default=dict)  # affected runs, counts, etc.
    created_at = Column(DateTime, default=utc_now, index=True)

    project = relationship("Project")
    user = relationship("User")


__all__ = [
    "SafeModeState",
    "KillSwitchLog",
    "SAFE_MODE_OFF",
    "SAFE_MODE_ACTIVE",
    "TARGET_GLOBAL",
    "TARGET_PROJECT",
    "ACTION_PAUSE",
    "ACTION_SAFE_MODE_OFF",
]
