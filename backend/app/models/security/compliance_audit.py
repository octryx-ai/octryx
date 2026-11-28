"""Compliance Audit Export and Evidence Records."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


AUDIT_APPROVAL = "approval"
AUDIT_PUBLISH_DECISION = "publish_decision"
AUDIT_EVAL_GATE = "eval_gate"
AUDIT_POLICY_CHANGE = "policy_change"
AUDIT_CONNECTOR_ACCESS = "connector_access"
AUDIT_KNOWLEDGE_PROMOTION = "knowledge_promotion"
AUDIT_RUNTIME_ACTION = "runtime_action"
AUDIT_SAFE_MODE = "safe_mode"
AUDIT_CREDENTIAL_ACCESS = "credential_access"
AUDIT_DATA_EXPORT = "data_export"
AUDIT_USER_ACCESS = "user_access"
AUDIT_ADMIN_CHANGE = "admin_change"
ALL_AUDIT_EVENT_TYPES = frozenset({
    AUDIT_APPROVAL, AUDIT_PUBLISH_DECISION, AUDIT_EVAL_GATE, AUDIT_POLICY_CHANGE,
    AUDIT_CONNECTOR_ACCESS, AUDIT_KNOWLEDGE_PROMOTION, AUDIT_RUNTIME_ACTION,
    AUDIT_SAFE_MODE, AUDIT_CREDENTIAL_ACCESS, AUDIT_DATA_EXPORT,
    AUDIT_USER_ACCESS, AUDIT_ADMIN_CHANGE,
})

OUTCOME_APPROVED = "approved"
OUTCOME_REJECTED = "rejected"
OUTCOME_BLOCKED = "blocked"
OUTCOME_ALLOWED = "allowed"
OUTCOME_ESCALATED = "escalated"
OUTCOME_REDACTED = "redacted"

EVIDENCE_STATUS_DRAFT = "draft"
EVIDENCE_STATUS_SEALED = "sealed"
EVIDENCE_STATUS_EXPORTED = "exported"


class ComplianceAuditRecord(WorkspaceBound, Base):
    """A structured compliance audit event: who did what on which resource, with what outcome."""
    __workspace_owners__ = {"session_id": "sessions"}

    __tablename__ = "compliance_audit_records"
    __table_args__ = (
        Index("ix_compliance_audit_project_type", "project_id", "event_type"),
        Index("ix_compliance_audit_actor", "actor_user_id"),
        Index("ix_compliance_audit_created", "created_at"),
        Index("ix_compliance_audit_resource", "resource_type", "resource_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    event_type = Column(String(40), nullable=False)
    outcome = Column(String(30), nullable=True)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actor_role = Column(String(100), nullable=True)
    resource_type = Column(String(60), nullable=False)
    resource_id = Column(String(36), nullable=True)
    resource_name = Column(String(220), nullable=True)
    # Structured payload — may be redacted on export
    details = Column(JSON, default=dict)
    contains_sensitive = Column(Boolean, nullable=False, default=False)
    redacted_fields = Column(JSON, default=list)  # list of field paths redacted
    classification_level = Column(String(30), nullable=True)
    data_classification_tag_id = Column(String(36), nullable=True)
    session_id = Column(String(36), nullable=True)
    incident_id = Column(String(100), nullable=True)
    request_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    project = relationship("Project")
    actor = relationship("User")


class EvidencePackage(WorkspaceBound, Base):
    """Exportable bundle of ComplianceAuditRecord rows for a review window."""

    __tablename__ = "evidence_packages"
    __table_args__ = (
        Index("ix_evidence_packages_project", "project_id"),
        Index("ix_evidence_packages_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    name = Column(String(220), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default=EVIDENCE_STATUS_DRAFT)
    period_from = Column(DateTime, nullable=True)
    period_to = Column(DateTime, nullable=True)
    filter_event_types = Column(JSON, default=list)
    filter_resource_types = Column(JSON, default=list)
    record_count = Column(String(20), nullable=True)
    redacted_count = Column(String(20), nullable=True)
    export_format = Column(String(20), nullable=True)  # json | csv
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    sealed_at = Column(DateTime, nullable=True)
    exported_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")
    creator = relationship("User")


__all__ = [
    "ComplianceAuditRecord",
    "EvidencePackage",
    "AUDIT_APPROVAL", "AUDIT_PUBLISH_DECISION", "AUDIT_EVAL_GATE",
    "AUDIT_POLICY_CHANGE", "AUDIT_CONNECTOR_ACCESS", "AUDIT_KNOWLEDGE_PROMOTION",
    "AUDIT_RUNTIME_ACTION", "AUDIT_SAFE_MODE", "AUDIT_CREDENTIAL_ACCESS",
    "AUDIT_DATA_EXPORT", "AUDIT_USER_ACCESS", "AUDIT_ADMIN_CHANGE",
    "ALL_AUDIT_EVENT_TYPES",
    "OUTCOME_APPROVED", "OUTCOME_REJECTED", "OUTCOME_BLOCKED", "OUTCOME_ALLOWED",
    "OUTCOME_ESCALATED", "OUTCOME_REDACTED",
    "EVIDENCE_STATUS_DRAFT", "EVIDENCE_STATUS_SEALED", "EVIDENCE_STATUS_EXPORTED",
]
