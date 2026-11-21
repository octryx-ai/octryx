import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class Scheduler(Base):
    __tablename__ = "schedulers"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    cron_expression = Column(String(100), nullable=False)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    task = relationship("Task")
    owner = relationship("User")
