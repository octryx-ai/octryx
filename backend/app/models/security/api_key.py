import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_user_id", "user_id"),
        Index("ix_api_keys_project_id", "project_id"),
        Index("ix_api_keys_key_hash", "key_hash", unique=True),
        Index("ix_api_keys_revoked_at", "revoked_at"),
        Index("ix_api_keys_expires_at", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    key_hash = Column(String(64), nullable=False, unique=True)
    key_prefix = Column(String(24), nullable=False)
    name = Column(String(160), nullable=False)
    scopes = Column(JSON, default=list, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
