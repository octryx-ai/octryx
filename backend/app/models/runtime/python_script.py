import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class SavedPythonScript(Base):
    __tablename__ = "saved_python_scripts"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(200), unique=True, nullable=False, index=True)
    purpose = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    code = Column(Text, nullable=False)
    runtime = Column(String(50), nullable=False, default="python3")
    arguments_schema = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    created_by = relationship("User")
