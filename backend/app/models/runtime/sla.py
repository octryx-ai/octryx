from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class SLADefinition(Base):
    __tablename__ = "sla_definitions"
    __table_args__ = (
        Index("ix_sla_definitions_task_id", "task_id"),
        Index("ix_sla_definitions_agent_type", "agent_type"),
        Index("ix_sla_definitions_active", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(200), nullable=False)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=True)
    agent_type = Column(String(50), nullable=True)
    max_duration_seconds = Column(Integer, nullable=False)
    alert_threshold = Column(Float, nullable=False, default=0.8)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    task = relationship("Task")


class SLABreach(Base):
    __tablename__ = "sla_breaches"
    __table_args__ = (
        Index("ix_sla_breaches_definition_created", "sla_definition_id", "created_at"),
        Index("ix_sla_breaches_task_run_breach_type", "task_run_id", "breach_type"),
        Index("ix_sla_breaches_severity_created", "severity", "created_at"),
        Index("ix_sla_breaches_is_resolved", "is_resolved"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    sla_definition_id = Column(String(36), ForeignKey("sla_definitions.id"), nullable=False)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=False)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    expected_at = Column(DateTime, nullable=False)
    actual_at = Column(DateTime, nullable=False)
    breach_type = Column(String(40), nullable=False)
    severity = Column(String(20), nullable=False, default="warning")
    is_resolved = Column(Boolean, nullable=False, default=False)
    notification_sent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    resolved_at = Column(DateTime, nullable=True)

    sla_definition = relationship("SLADefinition")
    task_run = relationship("TaskRun")
    task = relationship("Task")
