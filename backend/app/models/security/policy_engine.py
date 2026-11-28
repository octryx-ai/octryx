"""Cedar policy engine persistence: custom policy-set versions, the decision log and draft impact."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
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
from ..runtime.governed_revision import (
    REVISION_STATES,
    in_list,
    install_immutability_guard,
    published_requires_approval_check,
)

DIGEST_LENGTH = 71


def uuid_pk() -> str:
    return str(uuid.uuid4())


class PolicySetVersion(Base):
    __tablename__ = "policy_set_versions"
    __table_args__ = (
        CheckConstraint(in_list("state", REVISION_STATES), name="ck_policy_set_versions_state"),
        CheckConstraint("version >= 1", name="ck_policy_set_versions_version"),
        CheckConstraint(published_requires_approval_check(), name="ck_policy_set_versions_published"),
        Index("ix_policy_set_versions_state", "state"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    version = Column(Integer, nullable=False, unique=True)
    state = Column(String(16), nullable=False)
    policies_text = Column(Text, nullable=False)
    policy_ids = Column(JSON, nullable=False, default=list)
    digest = Column(String(DIGEST_LENGTH), nullable=False)
    schema_version = Column(String(32), nullable=False)
    note = Column(Text, nullable=True)
    base_version = Column(Integer, nullable=True)
    baseline_digest = Column(String(DIGEST_LENGTH), nullable=True)
    test_report = Column(JSON, nullable=True)
    # Custom content detectors and categories of this version (``content_detection.custom``); covered by
    # ``digest``. NULL: none.
    content_detectors = Column(JSON, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
    submitted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    approval_id = Column(String(36), ForeignKey("approvals.id"), nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    retired_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    retired_at = Column(DateTime, nullable=True)


install_immutability_guard(PolicySetVersion)


class PolicyDecisionLog(WorkspaceBound, Base):
    __workspace_owners__ = {"session_id": "sessions"}
    __workspace_column__ = "workspace_id"
    __tablename__ = "policy_decision_log"
    __table_args__ = (
        Index("ix_policy_decision_log_created", "created_at"),
        Index("ix_policy_decision_log_point_outcome", "point", "outcome"),
        Index("ix_policy_decision_log_workspace", "workspace_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    point = Column(String(40), nullable=False)
    action = Column(String(40), nullable=False)
    outcome = Column(String(20), nullable=False)
    mode = Column(String(10), nullable=False)
    workspace_id = Column(String(64), nullable=True)
    principal = Column(String(200), nullable=False)
    resource = Column(String(500), nullable=False)
    decision = Column(String(8), nullable=False)
    legacy_decision = Column(String(8), nullable=False)
    legacy_reason = Column(String(160), nullable=True)
    determining = Column(JSON, nullable=False, default=list)
    errors = Column(JSON, nullable=False, default=list)
    policy_set_digest = Column(String(DIGEST_LENGTH), nullable=True)
    custom_version = Column(Integer, nullable=True)
    schema_version = Column(String(32), nullable=False)
    latency_us = Column(Integer, nullable=False, default=0)
    # Content points: what the scan found (detector ids, counts, categories, sources, size, time — never
    # values, spans or hashes) and the obligation applied or that would have been applied.
    content = Column(JSON, nullable=True)
    obligation = Column(JSON, nullable=True)
    # Decision timeline (services/decisions): which gate decided, the run and session it belongs to, the deciding
    # rule, the reason given at the time (never overwritten), and for the approval lifecycle the approval and the
    # person who decided.
    gate = Column(String(40), nullable=True)
    session_id = Column(String(36), nullable=True, index=True)
    run_key = Column(String(120), nullable=True, index=True)
    rule = Column(String(300), nullable=True)
    reason = Column(String(300), nullable=True)
    approval_id = Column(String(36), nullable=True, index=True)
    actor_id = Column(String(36), nullable=True)


class PolicyDecisionCounter(WorkspaceBound, Base):
    """Allowed decisions per hour, gate, action and Workspace: allows are counted, not stored."""
    __workspace_column__ = "workspace_id"

    __tablename__ = "policy_decision_counters"
    __table_args__ = (
        UniqueConstraint("hour", "gate", "action", "workspace_id", name="uq_policy_decision_counters_key"),
        Index("ix_policy_decision_counters_hour", "hour"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    hour = Column(DateTime, nullable=False)
    gate = Column(String(40), nullable=False)
    action = Column(String(80), nullable=False)
    workspace_id = Column(String(64), nullable=False, default="")
    count = Column(Integer, nullable=False, default=0)




class PolicyDraftImpact(Base):
    """Would-deny counts of a draft's custom policies in live traffic, per hour (draft shadow)."""

    __tablename__ = "policy_draft_impact"
    __table_args__ = (
        UniqueConstraint("draft_digest", "policy_id", "point", "action", "hour", name="uq_policy_draft_impact_bucket"),
        Index("ix_policy_draft_impact_draft_hour", "draft_digest", "hour"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    draft_digest = Column(String(DIGEST_LENGTH), nullable=False)
    draft_version = Column(Integer, nullable=False)
    policy_id = Column(String(120), nullable=False)
    point = Column(String(40), nullable=False)
    action = Column(String(40), nullable=False)
    hour = Column(DateTime, nullable=False)
    count = Column(Integer, nullable=False, default=0)
    principals = Column(JSON, nullable=False, default=list)
    samples = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


class PolicyTestCase(Base):
    """A saved test-bench question with its expected answer; every draft save and every publish runs them all."""

    __tablename__ = "policy_test_cases"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(120), nullable=False)
    request = Column(JSON, nullable=False)
    expected = Column(String(8), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["PolicyDecisionLog", "PolicySetVersion", "PolicyTestCase"]
