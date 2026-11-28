import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class StoredSecret(WorkspaceBound, Base):
    __tablename__ = "stored_secrets"
    __table_args__ = (Index("ix_stored_secrets_expires_at", "expires_at"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(200), nullable=False)
    secret_type = Column(String(200), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    tool_name = Column(String(200), nullable=True, index=True)
    field_name = Column(String(200), nullable=True, index=True)
    encrypted_value = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_rotated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project")


class SecretRotationLog(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"secret_id": "stored_secrets"}
    __tablename__ = "secret_rotation_log"
    __table_args__ = (
        Index("ix_secret_rotation_log_secret_created", "secret_id", "created_at"),
        Index("ix_secret_rotation_log_action_created", "action", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    secret_id = Column(String(36), ForeignKey("stored_secrets.id"), nullable=False)
    action = Column(String(40), nullable=False, default="rotated")
    rotated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    previous_expires_at = Column(DateTime, nullable=True)
    new_expires_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    secret = relationship("StoredSecret")
    rotated_by_user = relationship("User")
