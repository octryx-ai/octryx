import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ContextBudgetProfile(Base):
    __tablename__ = "context_budget_profiles"
    __table_args__ = (Index("ix_context_budget_profiles_active_priority", "is_active", "priority"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(120), nullable=False)
    trigger_pattern = Column(String(255), nullable=False, index=True)
    base_budget = Column(Integer, nullable=False, default=4000)
    tool_budget = Column(Integer, nullable=False, default=0)
    history_budget = Column(Integer, nullable=False, default=0)
    entity_budget = Column(Integer, nullable=False, default=0)
    memory_budget = Column(Integer, nullable=False, default=0)
    priority = Column(Integer, nullable=False, default=100, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
