import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class APIRequestMetric(Base):
    __tablename__ = "api_request_metrics"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    endpoint = Column(String(255), nullable=False, index=True)
    method = Column(String(16), nullable=False, index=True)
    status_code = Column(Integer, nullable=False, index=True)
    duration_ms = Column(Integer, nullable=False)
    correlation_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)


class PlatformHealthCheck(Base):
    __tablename__ = "platform_health_checks"

    component = Column(String(100), primary_key=True)
    status = Column(String(32), nullable=False, index=True)
    response_time_ms = Column(Integer, nullable=False, default=0)
    error = Column(String(500), nullable=True)
    checked_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)


class BackgroundWorkerRunState(Base):
    __tablename__ = "background_worker_run_states"

    worker_name = Column(String(120), primary_key=True)
    owner = Column(String(120), nullable=False, index=True)
    status = Column(String(32), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    processed_count = Column(Integer, nullable=False, default=0)
    details_json = Column(JSON, default=dict, nullable=False)
    error = Column(Text, nullable=True)
    retryable = Column(Boolean, nullable=False, default=False)
    run_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)


class AgentTraceRun(Base):
    __tablename__ = "agent_trace_runs"
    __table_args__ = (
        Index("ix_agent_trace_runs_project_started", "project_id", "started_at"),
        Index("ix_agent_trace_runs_project_status", "project_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    trace_id = Column(String(64), nullable=False, unique=True, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    message_id = Column(String(36), ForeignKey("messages.id"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    agent_definition_id = Column(String(36), ForeignKey("agent_definitions.id"), nullable=True, index=True)
    flow_id = Column(String(120), nullable=True, index=True)
    run_kind = Column(String(80), nullable=False, default="agent", index=True)
    status = Column(String(40), nullable=False, default="running", index=True)
    started_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True, index=True)
    duration_ms = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Numeric(12, 6), nullable=False, default=0)
    quality_score = Column(Numeric(5, 4), nullable=True)
    error = Column(Text, nullable=True)
    trace_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)

    session = relationship("Session")
    spans = relationship("AgentTraceSpan", back_populates="run", cascade="all, delete-orphan")


class AgentTraceSpan(Base):
    __tablename__ = "agent_trace_spans"
    __table_args__ = (
        Index("ix_agent_trace_spans_run_started", "trace_run_id", "started_at"),
        Index("ix_agent_trace_spans_trace_type", "trace_id", "span_type"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    trace_run_id = Column(String(36), ForeignKey("agent_trace_runs.id"), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    span_id = Column(String(64), nullable=False, index=True)
    parent_span_id = Column(String(64), nullable=True, index=True)
    span_type = Column(String(60), nullable=False, index=True)
    name = Column(String(240), nullable=False)
    status = Column(String(40), nullable=False, default="running", index=True)
    started_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    ended_at = Column(DateTime, nullable=True, index=True)
    duration_ms = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Numeric(12, 6), nullable=False, default=0)
    input_json = Column(JSON, default=dict)
    output_json = Column(JSON, default=dict)
    span_metadata = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    run = relationship("AgentTraceRun", back_populates="spans")


class AgentTraceAlertRule(Base):
    __tablename__ = "agent_trace_alert_rules"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    condition_json = Column(JSON, default=dict)
    severity = Column(String(40), nullable=False, default="warning", index=True)
    notification_channel = Column(String(120), nullable=True)
    enabled = Column(Integer, nullable=False, default=1, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True)
