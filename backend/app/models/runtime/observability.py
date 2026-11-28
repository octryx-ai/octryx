import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text

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
