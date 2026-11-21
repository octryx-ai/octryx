"""Incident Response, Kill Switch, and Safe Mode models.

Provides:
  - SafeModeState: Global or project-scoped safe mode with kill switch capabilities
  - KillSwitchLog: Audit log for all kill switch / pause actions
  - PausedEntity: Tracks entities paused during an incident
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


# ── State constants ──────────────────────────────────────────────────────────

SAFE_MODE_OFF = "off"
SAFE_MODE_ACTIVE = "active"
SAFE_MODE_PARTIAL = "partial"  # only specific scopes paused
ALL_SAFE_MODE_STATES = frozenset({SAFE_MODE_OFF, SAFE_MODE_ACTIVE, SAFE_MODE_PARTIAL})

# Kill switch target types
TARGET_GLOBAL = "global"
TARGET_PROJECT = "project"
TARGET_FLOW = "flow"
TARGET_AGENT_CHAIN = "agent_chain"
TARGET_TASK = "task"
TARGET_SCHEDULER = "scheduler"
TARGET_MCP_SERVER = "mcp_server"
TARGET_CONNECTOR = "connector"
TARGET_PROVIDER = "provider"
ALL_TARGET_TYPES = frozenset({
    TARGET_GLOBAL, TARGET_PROJECT, TARGET_FLOW, TARGET_AGENT_CHAIN,
    TARGET_TASK, TARGET_SCHEDULER, TARGET_MCP_SERVER, TARGET_CONNECTOR,
    TARGET_PROVIDER,
})

# Kill switch actions
ACTION_PAUSE = "pause"
ACTION_RESUME = "resume"
ACTION_CANCEL = "cancel"
ACTION_SAFE_MODE_ON = "safe_mode_on"
ACTION_SAFE_MODE_OFF = "safe_mode_off"
ALL_ACTIONS = frozenset({ACTION_PAUSE, ACTION_RESUME, ACTION_CANCEL, ACTION_SAFE_MODE_ON, ACTION_SAFE_MODE_OFF})


class SafeModeState(Base):
    """Current safe mode state — global or per-project.

    When active, prevents new agent runs, flow executions, and connector calls.
    Optionally cancels running work.
    """

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
    # Behavior settings
    cancel_running_work = Column(Boolean, nullable=False, default=False)
    block_new_runs = Column(Boolean, nullable=False, default=True)
    notify_users = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")


class KillSwitchLog(Base):
    """Immutable audit log for every kill switch / pause / resume action.

    Provides compliance trail for incident response actions.
    """

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


class PausedEntity(Base):
    """Tracks entities currently paused by an incident response action.

    When safe mode is deactivated or a resume is issued, these records
    drive the automatic resume logic.
    """

    __tablename__ = "paused_entities"
    __table_args__ = (
        Index("ix_paused_entities_type_id", "entity_type", "entity_id", unique=True),
        Index("ix_paused_entities_incident", "incident_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    entity_type = Column(String(30), nullable=False)  # flow / agent_chain / task / etc.
    entity_id = Column(String(36), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    previous_is_active = Column(Boolean, nullable=True)  # to restore on resume
    paused_by_kill_switch_id = Column(String(36), ForeignKey("kill_switch_logs.id"), nullable=True)
    incident_id = Column(String(100), nullable=True)
    reason = Column(Text, nullable=True)
    paused_at = Column(DateTime, default=utc_now)
    resumed_at = Column(DateTime, nullable=True)

    project = relationship("Project")


__all__ = [
    "SafeModeState",
    "KillSwitchLog",
    "PausedEntity",
    "SAFE_MODE_OFF",
    "SAFE_MODE_ACTIVE",
    "SAFE_MODE_PARTIAL",
    "ALL_SAFE_MODE_STATES",
    "TARGET_GLOBAL",
    "TARGET_PROJECT",
    "TARGET_FLOW",
    "TARGET_AGENT_CHAIN",
    "TARGET_TASK",
    "TARGET_SCHEDULER",
    "TARGET_MCP_SERVER",
    "TARGET_CONNECTOR",
    "TARGET_PROVIDER",
    "ALL_TARGET_TYPES",
    "ACTION_PAUSE",
    "ACTION_RESUME",
    "ACTION_CANCEL",
    "ACTION_SAFE_MODE_ON",
    "ACTION_SAFE_MODE_OFF",
    "ALL_ACTIONS",
]
