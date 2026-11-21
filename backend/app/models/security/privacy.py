import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    __table_args__ = (Index("ix_retention_policies_entity_type", "entity_type"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    entity_type = Column(String(80), nullable=False)
    ttl_days = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False, default="delete")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    __table_args__ = (
        Index("ix_deletion_requests_status", "status"),
        Index("ix_deletion_requests_target_user_id", "target_user_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    target_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    reason = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)


class DataExport(Base):
    __tablename__ = "data_exports"
    __table_args__ = (
        Index("ix_data_exports_target_user_id", "target_user_id"),
        Index("ix_data_exports_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    target_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    file_url = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)
