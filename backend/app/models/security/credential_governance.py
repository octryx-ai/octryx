"""The append-only log of secret access events (``secret_access_audit_log``)."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class SecretAccessAuditLog(WorkspaceBound, Base):
    __tablename__ = "secret_access_audit_log"
    __table_args__ = (
        Index("ix_secret_access_audit_log_secret_action", "secret_id", "action"),
        Index("ix_secret_access_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_secret_access_audit_log_created", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    # Nullable: a row outlives the secret it is about (secret release detaches it).
    secret_id = Column(String(36), ForeignKey("stored_secrets.id"), nullable=True, index=True)
    action = Column(String(30), nullable=False, index=True)
    entity_type = Column(String(30), nullable=True)
    entity_id = Column(String(36), nullable=True)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    outcome = Column(String(20), nullable=False, default="success", index=True)
    # The secret's own Workspace, kept when the secret is released; no foreign key, so the record outlives it too.
    project_id = Column(String(36), nullable=True, index=True)
    principal = Column(String(200), nullable=True)
    purpose = Column(String(100), nullable=True)
    context_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    actor = relationship("User")
