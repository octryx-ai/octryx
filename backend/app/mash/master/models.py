"""MASH master-side SQLAlchemy models.

Tables live in the master's database and track platforms,
policies, audit logs, stats, peer permissions and quotas.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------


class MashPlatform(Base):
    __tablename__ = "mash_platforms"

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    platform_type = Column(String(60), nullable=False, default="octryx")
    status = Column(
        Enum("registered", "online", "offline", "suspended", name="mash_platform_status"),
        nullable=False,
        default="registered",
    )
    tags = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    capabilities_json = Column(JSON, nullable=True)
    registered_at = Column(DateTime, nullable=False, default=utc_now)
    last_seen_at = Column(DateTime, nullable=True)

    credentials = relationship("MashPlatformCredential", back_populates="platform", cascade="all, delete-orphan")
    stats = relationship("MashPlatformStats", back_populates="platform", cascade="all, delete-orphan")
    audit_logs = relationship("MashAuditLogEntry", back_populates="platform", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Platform Credentials (OAuth2 client credentials)
# ---------------------------------------------------------------------------


class MashPlatformCredential(Base):
    __tablename__ = "mash_platform_credentials"

    id = Column(String(36), primary_key=True, default=_uuid)
    platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=False, index=True)
    client_id = Column(String(120), unique=True, nullable=False)
    client_secret_hash = Column(String(256), nullable=False)
    scopes = Column(JSON, nullable=False, default=list)
    issued_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    platform = relationship("MashPlatform", back_populates="credentials")


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class MashPolicy(Base):
    __tablename__ = "mash_policies"
    __table_args__ = (Index("ix_mash_policy_key_version", "key", "version", unique=True),)

    id = Column(String(36), primary_key=True, default=_uuid)
    key = Column(String(200), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String(40), nullable=False)
    rules = Column(JSON, nullable=False, default=dict)
    status = Column(
        Enum("draft", "released", "deprecated", name="mash_policy_status"),
        nullable=False,
        default="draft",
    )
    scope = Column(String(40), nullable=False, default="global")
    created_at = Column(DateTime, nullable=False, default=utc_now)
    released_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Policy Assignment (which platform gets which policy at what priority)
# ---------------------------------------------------------------------------


class MashPolicyAssignment(Base):
    __tablename__ = "mash_policy_assignments"
    __table_args__ = (
        Index("ix_mash_policy_assign_platform", "platform_id", "policy_id", unique=True),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=True)
    policy_id = Column(String(36), ForeignKey("mash_policies.id"), nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    assigned_at = Column(DateTime, nullable=False, default=utc_now)


# ---------------------------------------------------------------------------
# Master Change Log (monotonic sequence for incremental sync)
# ---------------------------------------------------------------------------


class MashChangeLog(Base):
    __tablename__ = "mash_changelog"

    sequence = Column(BigInteger, primary_key=True, autoincrement=True)
    resource_type = Column(
        Enum("policy", name="mash_resource_type"),
        nullable=False,
    )
    resource_key = Column(String(200), nullable=False, index=True)
    resource_version = Column(String(40), nullable=False)
    change_type = Column(
        Enum("created", "updated", "deprecated", "rolled_back", name="mash_change_type"),
        nullable=False,
    )
    payload = Column(JSON, nullable=False)
    checksum = Column(String(80), nullable=False)
    changed_at = Column(DateTime, nullable=False, default=utc_now)


# ---------------------------------------------------------------------------
# Audit Log Entry (received from platforms)
# ---------------------------------------------------------------------------


class MashAuditLogEntry(Base):
    __tablename__ = "mash_audit_log"
    __table_args__ = (Index("ix_mash_audit_platform_time", "platform_id", "occurred_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=False, index=True)
    severity = Column(
        Enum("info", "warning", "critical", name="mash_severity"),
        nullable=False,
        default="info",
    )
    category = Column(String(60), nullable=False, index=True)
    event_type = Column(String(120), nullable=False)
    payload = Column(JSON, nullable=True)
    occurred_at = Column(DateTime, nullable=False)
    received_at = Column(DateTime, nullable=False, default=utc_now)

    platform = relationship("MashPlatform", back_populates="audit_logs")


# ---------------------------------------------------------------------------
# Platform Stats (aggregated usage from platforms)
# ---------------------------------------------------------------------------


class MashPlatformStats(Base):
    __tablename__ = "mash_platform_stats"
    __table_args__ = (Index("ix_mash_stats_platform_period", "platform_id", "period_start"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=False, index=True)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    messages_total = Column(Integer, nullable=False, default=0)
    messages_ai = Column(Integer, nullable=False, default=0)
    token_usage_input = Column(BigInteger, nullable=False, default=0)
    token_usage_output = Column(BigInteger, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)
    model_versions = Column(JSON, nullable=True)
    captured_at = Column(DateTime, nullable=False, default=utc_now)

    platform = relationship("MashPlatform", back_populates="stats")


# ---------------------------------------------------------------------------
# Peer Permission
# ---------------------------------------------------------------------------


class MashPeerPermission(Base):
    __tablename__ = "mash_peer_permissions"
    __table_args__ = (
        Index("ix_mash_peer_from_to", "from_platform_id", "to_platform_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    from_platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=False)
    to_platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=False)
    permission_type = Column(String(60), nullable=False)
    scope_json = Column(JSON, nullable=True)
    granted_by = Column(String(36), nullable=True)
    granted_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Platform Quota (rate limits)
# ---------------------------------------------------------------------------


class MashPlatformQuota(Base):
    __tablename__ = "mash_platform_quotas"

    id = Column(String(36), primary_key=True, default=_uuid)
    platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=False, unique=True)
    max_requests_per_minute = Column(Integer, nullable=False, default=60)
    max_audit_events_per_hour = Column(Integer, nullable=False, default=5000)
    max_stats_ingests_per_hour = Column(Integer, nullable=False, default=100)
    max_peer_requests_per_hour = Column(Integer, nullable=False, default=50)
    max_ws_connections = Column(Integer, nullable=False, default=3)


# ---------------------------------------------------------------------------
# Platform Budget (token / cost quotas)
# ---------------------------------------------------------------------------


class MashPlatformBudget(Base):
    __tablename__ = "mash_platform_budgets"

    id = Column(String(36), primary_key=True, default=_uuid)
    platform_id = Column(String(36), ForeignKey("mash_platforms.id"), nullable=False, unique=True)
    period = Column(
        Enum("daily", "weekly", "monthly", name="mash_budget_period"),
        nullable=False,
        default="monthly",
    )
    max_input_tokens = Column(BigInteger, nullable=True)
    max_output_tokens = Column(BigInteger, nullable=True)
    max_cost_usd = Column(Float, nullable=True)
    alert_threshold_pct = Column(Integer, nullable=False, default=80)
    hard_limit = Column(Boolean, nullable=False, default=False)


# ---------------------------------------------------------------------------
# Idempotency Record (for dedup of audit/stats push)
# ---------------------------------------------------------------------------


class MashIdempotencyRecord(Base):
    __tablename__ = "mash_idempotency"

    key = Column(String(80), primary_key=True)
    response_hash = Column(String(80), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    expires_at = Column(DateTime, nullable=False)
