"""Master Control Plane to Slave Project Platform governance models.

Architecture:
  - Master governs approved baseline assets (flow templates,
    policies, tool configurations) via the Agent/Flow Registry.
  - Slave Project Platforms inherit and run independently. They own all
    project-local data: secrets, connectors, Knowledge, Work Packages, runs,
    Agent Learning.
  - Secrets are NEVER migrated, exported, or included in any rollout or
    telemetry payload.
  - Controlled, anonymized compliance summaries may be sent from Slave → Master.

Inheritance modes:
  enforced        — Slave must use the Master version; cannot override.
  override_allowed — Slave starts from Master baseline; local override permitted.
  extension_only  — Slave may only add new configuration, not change existing.
  advisory        — Master provides suggestion; Slave decides independently.
  disabled        — Asset is not pushed to this Slave at all.

Rollout statuses:
  draft → preview → dry_run_passed → approved → applying → applied
  → monitoring → completed | rolled_back | failed
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Inheritance mode constants
# ---------------------------------------------------------------------------

INHERIT_ENFORCED = "enforced"
INHERIT_OVERRIDE_ALLOWED = "override_allowed"
INHERIT_EXTENSION_ONLY = "extension_only"
INHERIT_ADVISORY = "advisory"
INHERIT_DISABLED = "disabled"

INHERIT_MODES = {
    INHERIT_ENFORCED,
    INHERIT_OVERRIDE_ALLOWED,
    INHERIT_EXTENSION_ONLY,
    INHERIT_ADVISORY,
    INHERIT_DISABLED,
}

# ---------------------------------------------------------------------------
# Rollout status constants
# ---------------------------------------------------------------------------

ROLLOUT_DRAFT = "draft"
ROLLOUT_PREVIEW = "preview"
ROLLOUT_DRY_RUN_PASSED = "dry_run_passed"
ROLLOUT_APPROVED = "approved"
ROLLOUT_APPLYING = "applying"
ROLLOUT_APPLIED = "applied"
ROLLOUT_MONITORING = "monitoring"
ROLLOUT_COMPLETED = "completed"
ROLLOUT_ROLLED_BACK = "rolled_back"
ROLLOUT_FAILED = "failed"

ROLLOUT_TERMINAL = {ROLLOUT_COMPLETED, ROLLOUT_ROLLED_BACK, ROLLOUT_FAILED}

ROLLOUT_TRANSITIONS: dict[str, set[str]] = {
    ROLLOUT_DRAFT: {ROLLOUT_PREVIEW},
    ROLLOUT_PREVIEW: {ROLLOUT_DRY_RUN_PASSED, ROLLOUT_DRAFT},
    ROLLOUT_DRY_RUN_PASSED: {ROLLOUT_APPROVED, ROLLOUT_DRAFT},
    ROLLOUT_APPROVED: {ROLLOUT_APPLYING},
    ROLLOUT_APPLYING: {ROLLOUT_APPLIED, ROLLOUT_FAILED},
    ROLLOUT_APPLIED: {ROLLOUT_MONITORING, ROLLOUT_ROLLED_BACK},
    ROLLOUT_MONITORING: {ROLLOUT_COMPLETED, ROLLOUT_ROLLED_BACK},
    ROLLOUT_COMPLETED: set(),
    ROLLOUT_ROLLED_BACK: set(),
    ROLLOUT_FAILED: {ROLLOUT_DRAFT},
}

# ---------------------------------------------------------------------------
# Drift status constants
# ---------------------------------------------------------------------------

DRIFT_NONE = "none"
DRIFT_DETECTED = "detected"
DRIFT_INTENTIONAL = "intentional"
DRIFT_CONFLICT = "conflict"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SlaveProjectPlatform(Base):
    """Registration of a Slave Project Platform under Master governance.

    One record per Slave platform. Holds the default inheritance mode and
    metadata about the Slave (endpoint hint, last contact, compliance status).
    """

    __tablename__ = "slave_project_platforms"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_slave_project_platforms_project"),
        Index("ix_slave_project_platforms_active", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    # The Project record that represents this Slave platform
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    display_name = Column(String(220), nullable=False)
    description = Column(Text, default="")
    # Default inheritance mode applied to all assets unless overridden per-asset
    default_inheritance_mode = Column(String(30), nullable=False, default=INHERIT_ADVISORY)
    # Hint for Master to know where this Slave runs (URL, region, etc.)
    # Never used to push secrets; purely informational.
    endpoint_hint = Column(String(500), nullable=True)
    # Last time this Slave submitted a compliance summary
    last_compliance_at = Column(DateTime, nullable=True)
    # Aggregate drift status across all governed assets
    drift_status = Column(String(20), nullable=False, default=DRIFT_NONE)
    is_active = Column(Boolean, nullable=False, default=True)
    registered_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    project = relationship("Project")
    registrar = relationship("User")
    rollout_plans = relationship(
        "MasterRolloutPlan",
        back_populates="slave_platform",
        cascade="all, delete-orphan",
    )
    compliance_summaries = relationship(
        "SlaveComplianceSummary",
        back_populates="slave_platform",
        cascade="all, delete-orphan",
        order_by="SlaveComplianceSummary.submitted_at.desc()",
    )


class MasterRolloutPlan(Base):
    """A planned rollout of one or more registry assets to a specific Slave platform.

    Supports preview, dry-run, apply, monitor, and rollback phases.
    A rollout plan is always scoped to one Slave; multi-Slave rollouts use
    multiple plans (one per Slave) to enable independent tracking.
    """

    __tablename__ = "master_rollout_plans"
    __table_args__ = (
        Index("ix_master_rollout_plans_slave_status", "slave_platform_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    slave_platform_id = Column(String(36), ForeignKey("slave_project_platforms.id"), nullable=False, index=True)
    name = Column(String(220), nullable=False)
    description = Column(Text, default="")
    status = Column(String(30), nullable=False, default=ROLLOUT_DRAFT, index=True)
    # Whether this was run as a dry-run (no real changes applied)
    is_dry_run = Column(Boolean, nullable=False, default=False)
    # Preview / dry-run report stored here
    preview_report = Column(JSON, nullable=False, default=dict)
    # Conflicts detected during preview or dry-run
    conflict_report = Column(JSON, nullable=False, default=dict)
    # Applied changes summary (filled after apply)
    apply_report = Column(JSON, nullable=False, default=dict)
    # Rollback metadata (filled if rolled back)
    rollback_report = Column(JSON, nullable=False, default=dict)
    # Notes / change summary
    notes = Column(Text, default="")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    applied_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    rolled_back_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    approved_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    slave_platform = relationship("SlaveProjectPlatform", back_populates="rollout_plans")
    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    applier = relationship("User", foreign_keys=[applied_by])
    rollback_actor = relationship("User", foreign_keys=[rolled_back_by])
    entries = relationship(
        "MasterRolloutEntry",
        back_populates="plan",
        cascade="all, delete-orphan",
    )


class MasterRolloutEntry(Base):
    """One asset within a rollout plan (agent or flow registry version).

    Tracks per-asset inheritance mode, conflict, and drift status.
    """

    __tablename__ = "master_rollout_entries"
    __table_args__ = (
        UniqueConstraint("plan_id", "asset_type", "asset_version_id", name="uq_master_rollout_entries_plan_asset"),
        Index("ix_master_rollout_entries_drift", "drift_status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    plan_id = Column(String(36), ForeignKey("master_rollout_plans.id"), nullable=False, index=True)
    # "agent" or "flow"
    asset_type = Column(String(20), nullable=False)
    # ID of the FlowRegistryVersion
    asset_version_id = Column(String(36), nullable=False, index=True)
    # Inheritance mode applied to this specific asset
    inheritance_mode = Column(String(30), nullable=False, default=INHERIT_ADVISORY)
    # Conflict detected for this entry during preview/dry-run
    has_conflict = Column(Boolean, nullable=False, default=False)
    conflict_detail = Column(JSON, nullable=False, default=dict)
    # Drift status compared to current Slave state
    drift_status = Column(String(20), nullable=False, default=DRIFT_NONE)
    drift_detail = Column(JSON, nullable=False, default=dict)
    # Status of this specific entry after apply
    apply_status = Column(String(20), nullable=False, default="pending")
    apply_detail = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    plan = relationship("MasterRolloutPlan", back_populates="entries")


class SlaveComplianceSummary(Base):
    """Controlled, anonymized telemetry submitted from Slave to Master.

    IMPORTANT: This record MUST NOT contain:
    - Secrets or credentials
    - Raw project-local Knowledge content
    - Work Package details
    - Agent Learning data
    - Session messages or run details

    Only aggregate statistics, version alignment, and policy compliance
    summaries are permitted.
    """

    __tablename__ = "slave_compliance_summaries"

    id = Column(String(36), primary_key=True, default=_uuid)
    slave_platform_id = Column(String(36), ForeignKey("slave_project_platforms.id"), nullable=False, index=True)
    # Aliveness: total active agents, active sessions, last run
    active_agent_count = Column(Integer, nullable=False, default=0)
    active_session_count = Column(Integer, nullable=False, default=0)
    last_run_at = Column(DateTime, nullable=True)
    # Registry alignment: which agent/flow versions are deployed
    deployed_agent_versions = Column(JSON, nullable=False, default=dict)   # {entry_key: version_int}
    deployed_flow_versions = Column(JSON, nullable=False, default=dict)
    # Policy compliance flags (booleans only — no raw data)
    policies_compliant = Column(Boolean, nullable=False, default=True)
    compliance_flags = Column(JSON, nullable=False, default=dict)  # {policy_name: bool}
    # Drift summary (counts, no content)
    drifted_asset_count = Column(Integer, nullable=False, default=0)
    # Free-form notes from Slave admin (optional, no secrets)
    notes = Column(Text, default="")
    submitted_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=False)

    slave_platform = relationship("SlaveProjectPlatform", back_populates="compliance_summaries")
    submitter = relationship("User")
