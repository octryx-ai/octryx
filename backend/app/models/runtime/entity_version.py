import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class EntityVersion(Base):
    __tablename__ = "entity_versions"
    __table_args__ = (
        Index("ix_entity_versions_entity", "entity_type", "entity_id", "version", unique=True),
        Index("ix_entity_versions_changed_by", "changed_by"),
        Index("ix_entity_versions_changed_at", "changed_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    entity_type = Column(String(60), nullable=False)
    entity_id = Column(String(36), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(JSON, nullable=False)
    changed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime, default=utc_now, nullable=False)
