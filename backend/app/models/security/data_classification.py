"""Data classification, retention, and redaction models.

Provides:
  DataClassificationPolicy — default policy per entity type (retention, export, redaction)
  DataClassificationTag    — per-record classification label with PII metadata
  DataRedactionLog         — immutable log of every redaction event

Classification levels (ascending sensitivity):
  public | internal | confidential | restricted | secret

PII type tags:
  email | phone | ssn | credit_card | iban | ip_address | name |
  address | date_of_birth | health | biometric | national_id | custom

Entity types covered:
  session | message | trace_span | turn_trace | knowledge_map |
  evaluation | document | connector_payload | agent_output | hcm_data |
  legal_data | pm_data
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now

# ---------------------------------------------------------------------------
# Classification level constants
# ---------------------------------------------------------------------------

CLASSIFICATION_PUBLIC: Final[str] = "public"
CLASSIFICATION_INTERNAL: Final[str] = "internal"
CLASSIFICATION_CONFIDENTIAL: Final[str] = "confidential"
CLASSIFICATION_RESTRICTED: Final[str] = "restricted"
CLASSIFICATION_SECRET: Final[str] = "secret"

CLASSIFICATION_LEVELS: Final[tuple[str, ...]] = (
    CLASSIFICATION_PUBLIC,
    CLASSIFICATION_INTERNAL,
    CLASSIFICATION_CONFIDENTIAL,
    CLASSIFICATION_RESTRICTED,
    CLASSIFICATION_SECRET,
)

# ---------------------------------------------------------------------------
# PII type constants
# ---------------------------------------------------------------------------

PII_EMAIL: Final[str] = "email"
PII_PHONE: Final[str] = "phone"
PII_SSN: Final[str] = "ssn"
PII_CREDIT_CARD: Final[str] = "credit_card"
PII_IBAN: Final[str] = "iban"
PII_IP_ADDRESS: Final[str] = "ip_address"
PII_NAME: Final[str] = "name"
PII_ADDRESS: Final[str] = "address"
PII_DATE_OF_BIRTH: Final[str] = "date_of_birth"
PII_HEALTH: Final[str] = "health"
PII_BIOMETRIC: Final[str] = "biometric"
PII_NATIONAL_ID: Final[str] = "national_id"

ALL_PII_TYPES: Final[frozenset[str]] = frozenset(
    {
        PII_EMAIL, PII_PHONE, PII_SSN, PII_CREDIT_CARD, PII_IBAN,
        PII_IP_ADDRESS, PII_NAME, PII_ADDRESS, PII_DATE_OF_BIRTH,
        PII_HEALTH, PII_BIOMETRIC, PII_NATIONAL_ID,
    }
)

# ---------------------------------------------------------------------------
# Entity type constants
# ---------------------------------------------------------------------------

ENTITY_SESSION: Final[str] = "session"
ENTITY_MESSAGE: Final[str] = "message"
ENTITY_TRACE_SPAN: Final[str] = "trace_span"
ENTITY_TURN_TRACE: Final[str] = "turn_trace"
ENTITY_KNOWLEDGE_MAP: Final[str] = "knowledge_map"
ENTITY_EVALUATION: Final[str] = "evaluation"
ENTITY_DOCUMENT: Final[str] = "document"
ENTITY_CONNECTOR_PAYLOAD: Final[str] = "connector_payload"
ENTITY_AGENT_OUTPUT: Final[str] = "agent_output"
ENTITY_HCM_DATA: Final[str] = "hcm_data"
ENTITY_LEGAL_DATA: Final[str] = "legal_data"
ENTITY_PM_DATA: Final[str] = "pm_data"

ALL_ENTITY_TYPES: Final[frozenset[str]] = frozenset(
    {
        ENTITY_SESSION, ENTITY_MESSAGE, ENTITY_TRACE_SPAN, ENTITY_TURN_TRACE,
        ENTITY_KNOWLEDGE_MAP, ENTITY_EVALUATION, ENTITY_DOCUMENT,
        ENTITY_CONNECTOR_PAYLOAD, ENTITY_AGENT_OUTPUT,
        ENTITY_HCM_DATA, ENTITY_LEGAL_DATA, ENTITY_PM_DATA,
    }
)

# ---------------------------------------------------------------------------
# Export action constants
# ---------------------------------------------------------------------------

EXPORT_ACTION_ALLOW: Final[str] = "allow"
EXPORT_ACTION_REDACT: Final[str] = "redact"
EXPORT_ACTION_DENY: Final[str] = "deny"

REDACT_ACTION_LOG: Final[str] = "log"


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DataClassificationPolicy(Base):
    """Default classification policy for a given entity type.

    Defines what happens to records of this type at export, retention, and
    redaction time.  One active policy per entity_type is the norm; additional
    rows can be keyed by project_id for project-level overrides.
    """

    __tablename__ = "data_classification_policies"
    __table_args__ = (
        Index("ix_dcp_entity_type", "entity_type"),
        Index("ix_dcp_project_id", "project_id"),
        Index("ix_dcp_classification", "default_classification"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)

    # Which entity type this policy governs
    entity_type = Column(String(80), nullable=False)

    # Optional project-scoped override (NULL = platform-wide default)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)

    # Default classification level applied when no explicit tag exists
    default_classification = Column(String(30), nullable=False, default=CLASSIFICATION_INTERNAL)

    # Retention window in days (NULL = keep indefinitely)
    retention_days = Column(Integer, nullable=True)

    # What to do at export time: allow | redact | deny
    export_action = Column(String(20), nullable=False, default=EXPORT_ACTION_ALLOW)

    # Whether to automatically detect and redact PII before storing
    auto_redact_pii = Column(Boolean, nullable=False, default=False)

    # Whether export requires explicit audit log entry
    require_export_audit = Column(Boolean, nullable=False, default=True)

    # Data residency constraint (NULL = unrestricted)
    data_residency = Column(String(100), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class DataClassificationTag(Base):
    """Per-record classification tag.

    Attached to any entity by (entity_type, entity_id).  Carries the
    effective classification level, detected PII types, retention override,
    and redaction state.
    """

    __tablename__ = "data_classification_tags"
    __table_args__ = (
        Index("ix_dct_entity", "entity_type", "entity_id"),
        Index("ix_dct_classification", "classification"),
        Index("ix_dct_project_id", "project_id"),
        Index("ix_dct_pii_present", "pii_detected"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)

    # The entity being classified
    entity_type = Column(String(80), nullable=False)
    entity_id = Column(String(200), nullable=False)

    # Optional project scope (for filtering / project-level audits)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Effective classification level
    classification = Column(String(30), nullable=False, default=CLASSIFICATION_INTERNAL)

    # True if any PII was detected or explicitly declared
    pii_detected = Column(Boolean, nullable=False, default=False)

    # List of PII types detected (e.g. ["email", "phone"])
    pii_types = Column(JSON, nullable=False, default=list)

    # Retention override in days (NULL = use policy default)
    retention_days_override = Column(Integer, nullable=True)

    # Data residency constraint for this specific record (NULL = inherit policy)
    data_residency = Column(String(100), nullable=True)

    # Whether redaction has been applied to the stored content
    redaction_applied = Column(Boolean, nullable=False, default=False)

    # Which fields were redacted and how ({"field": "mask_type", ...})
    redaction_config = Column(JSON, nullable=False, default=dict)

    # Free-form sensitivity tags (e.g. ["hcm:employee_data", "legal:privileged"])
    sensitivity_tags = Column(JSON, nullable=False, default=list)

    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    classified_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class DataRedactionLog(Base):
    """Immutable log of every redaction event.

    Written every time content is redacted — either at write time (auto_redact_pii)
    or at export time (export_action=redact).  Never deleted.
    """

    __tablename__ = "data_redaction_logs"
    __table_args__ = (
        Index("ix_drl_entity", "entity_type", "entity_id"),
        Index("ix_drl_classification", "classification"),
        Index("ix_drl_created_at", "created_at"),
        Index("ix_drl_redaction_reason", "redaction_reason"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)

    entity_type = Column(String(80), nullable=False)
    entity_id = Column(String(200), nullable=False)

    # What triggered the redaction: auto_pii | export | manual | policy
    redaction_reason = Column(String(50), nullable=False)

    # The classification level at the time of redaction
    classification = Column(String(30), nullable=False)

    # Which PII types were detected/redacted
    pii_types_redacted = Column(JSON, nullable=False, default=list)

    # Which fields were touched (paths like "content.email")
    redacted_fields = Column(JSON, nullable=False, default=list)

    # Actor who triggered the redaction (NULL = system/automatic)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    context_json = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime, default=utc_now, index=True)
