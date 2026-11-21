import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class PromptConfigRevision(Base):
    """Immutable prompt configuration revision for audit and rollback."""

    __tablename__ = "prompt_config_revisions"
    __table_args__ = (
        Index(
            "ix_prompt_config_revisions_scope_config_version",
            "scope_type",
            "scope_id",
            "config_key",
            "version",
        ),
        Index("ix_prompt_config_revisions_config_key", "config_key"),
        Index("ix_prompt_config_revisions_created_at", "created_at"),
        Index("ix_prompt_config_revisions_created_by", "created_by"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    scope_type = Column(String(30), nullable=False)
    scope_id = Column(String(200), nullable=True)
    config_key = Column(String(240), nullable=False)
    variant_key = Column(String(80), nullable=True)
    version = Column(Integer, nullable=False)
    value = Column(Text, nullable=True)
    value_checksum = Column(String(64), nullable=False)
    change_source = Column(String(60), nullable=False, default="manual")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    revision_metadata = Column("metadata", JSON, default=dict)
