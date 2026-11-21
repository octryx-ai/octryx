import uuid

from sqlalchemy import JSON, Column, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class WorkerPoolConfig(Base):
    __tablename__ = "worker_pool_config"
    __table_args__ = (Index("ix_worker_pool_config_project_id", "project_id", unique=True),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    min_workers = Column(Integer, nullable=False, default=1)
    max_workers = Column(Integer, nullable=False, default=10)
    current_workers = Column(Integer, nullable=False, default=1)
    scale_up_threshold = Column(Integer, nullable=False, default=5)
    scale_down_threshold = Column(Integer, nullable=False, default=1)
    scale_up_cooldown_minutes = Column(Integer, nullable=False, default=5)
    scale_down_cooldown_minutes = Column(Integer, nullable=False, default=15)
    max_llm_cost_per_hour = Column(Numeric(10, 4), nullable=True)
    last_scale_action = Column(String(20), nullable=True)
    last_scale_at = Column(DateTime, nullable=True)
    queue_backend = Column(String(20), nullable=False, default="database")
    redis_url = Column(String(500), nullable=True)
    hpa_target_queue_depth = Column(Integer, nullable=False, default=5)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    project = relationship("Project")


class WorkerCapacityLog(Base):
    __tablename__ = "worker_capacity_log"
    __table_args__ = (Index("ix_worker_capacity_log_worker_recorded", "worker_id", "recorded_at"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    queue_depth = Column(Integer, nullable=False, default=0)
    active_tasks = Column(Integer, nullable=False, default=0)
    avg_task_duration_minutes = Column(Float, nullable=True)
    llm_cost_last_hour = Column(Numeric(10, 4), nullable=False, default=0)
    cpu_pressure = Column(String(10), nullable=False, default="low")
    recorded_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker")


class WorkerDomainExpertise(Base):
    __tablename__ = "worker_domain_expertise"
    __table_args__ = (
        Index("ix_worker_domain_expertise_domain", "domain"),
        Index("ix_worker_domain_expertise_worker_domain", "worker_id", "domain", unique=True),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    domain = Column(String(50), nullable=False)
    expertise_level = Column(String(20), nullable=False, default="beginner")
    tasks_completed = Column(Integer, nullable=False, default=0)
    avg_resolution_time_minutes = Column(Float, nullable=True)
    success_rate = Column(Float, nullable=False, default=0.5)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    worker = relationship("AgentWorker")


class TaskRoutingRule(Base):
    __tablename__ = "task_routing_rules"
    __table_args__ = (
        Index("ix_task_routing_rules_project_active", "project_id", "is_active"),
        Index("ix_task_routing_rules_priority", "priority"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    priority = Column(Integer, nullable=False, default=100)
    condition_type = Column(String(50), nullable=False)
    condition_config = Column(JSON, default=dict)
    target_type = Column(String(20), nullable=False, default="worker_pool")
    target_config = Column(JSON, default=dict)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utc_now, index=True)

    project = relationship("Project")


class WorkerRateLimit(Base):
    __tablename__ = "worker_rate_limits"
    __table_args__ = (Index("ix_worker_rate_limits_project_id", "project_id", unique=True),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    max_requests_per_minute = Column(Integer, nullable=False, default=60)
    max_tokens_per_hour = Column(Integer, nullable=False, default=500000)
    max_cost_per_hour = Column(Numeric(10, 4), nullable=False, default=10)
    max_cost_per_day = Column(Numeric(10, 4), nullable=False, default=50)
    on_minute_limit = Column(String(20), nullable=False, default="queue")
    on_cost_limit = Column(String(30), nullable=False, default="pause_low_priority")
    current_rpm = Column(Float, nullable=False, default=0)
    current_hour_tokens = Column(Integer, nullable=False, default=0)
    current_hour_cost = Column(Numeric(10, 4), nullable=False, default=0)
    current_day_cost = Column(Numeric(10, 4), nullable=False, default=0)
    reset_minute_at = Column(DateTime, nullable=True)
    reset_hour_at = Column(DateTime, nullable=True)
    reset_day_at = Column(Date, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    project = relationship("Project")


class DistributedWorkerRegistration(Base):
    __tablename__ = "distributed_workers"
    __table_args__ = (
        Index("ix_distributed_workers_project_active", "project_id", "is_active"),
        Index("ix_distributed_workers_heartbeat", "last_heartbeat"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    backend = Column(String(20), nullable=False, default="database")
    status = Column(String(20), nullable=False, default="starting")
    domains = Column(JSON, default=list)
    capabilities = Column(JSON, default=dict)
    pod_name = Column(String(255), nullable=True)
    queue_name = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    is_active = Column(Integer, nullable=False, default=1)
    registered_at = Column(DateTime, default=utc_now, index=True)
    last_heartbeat = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker")
    project = relationship("Project")
