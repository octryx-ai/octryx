import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    key = Column(String(120), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    rollout_percentage = Column(Integer, nullable=False, default=100)
    allowed_projects = Column(JSON, nullable=False, default=list)
    allowed_roles = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)
