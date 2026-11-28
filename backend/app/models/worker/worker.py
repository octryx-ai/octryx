import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class AgentWorker(WorkspaceBound, Base):
    __tablename__ = "agent_workers"
    __table_args__ = (
        Index("ix_agent_workers_project_active", "project_id", "is_active"),
        Index("ix_agent_workers_role", "role"),
        Index("ix_agent_workers_autonomy_level", "autonomy_level"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    avatar_url = Column(String(500), nullable=True)
    schedule_type = Column(String(30), nullable=False, default="always_on")
    timezone = Column(String(50), nullable=False, default="UTC")
    work_hours_start = Column(Time, nullable=True)
    work_hours_end = Column(Time, nullable=True)
    on_call_schedule = Column(JSON, default=dict)
    autonomy_level = Column(String(20), nullable=False, default="supervised")
    allowed_actions = Column(JSON, default=list)
    forbidden_actions = Column(JSON, default=list)
    report_channel = Column(String(100), nullable=True)
    escalation_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    report_schedule = Column(String(50), nullable=True)
    trust_score = Column(Float, nullable=False, default=0.5)
    total_tasks_completed = Column(Integer, nullable=False, default=0)
    total_incidents_resolved = Column(Integer, nullable=False, default=0)
    avg_resolution_time_minutes = Column(Float, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    project = relationship("Project")
    escalation_user = relationship("User", foreign_keys=[escalation_user_id])
    onboarding = relationship("WorkerOnboarding", back_populates="worker", uselist=False, cascade="all, delete-orphan")
    runtime_state = relationship(
        "WorkerRuntimeState", back_populates="worker", uselist=False, cascade="all, delete-orphan"
    )
    monitors = relationship("WorkerMonitor", back_populates="worker", cascade="all, delete-orphan")
    trust_events = relationship("WorkerTrustEvent", back_populates="worker", cascade="all, delete-orphan")
    shifts = relationship("WorkerShift", back_populates="worker", cascade="all, delete-orphan")
    daily_agendas = relationship("WorkerDailyAgenda", back_populates="worker", cascade="all, delete-orphan")
    escalation_rules = relationship("WorkerEscalationRule", back_populates="worker", cascade="all, delete-orphan")
    escalations = relationship("WorkerEscalation", back_populates="worker", cascade="all, delete-orphan")
    reports = relationship("WorkerReport", back_populates="worker", cascade="all, delete-orphan")
    learnings = relationship("WorkerLearning", back_populates="worker", cascade="all, delete-orphan")
    outgoing_delegations = relationship(
        "WorkerDelegation",
        back_populates="from_worker",
        cascade="all, delete-orphan",
        foreign_keys="WorkerDelegation.from_worker_id",
    )
    incoming_delegations = relationship(
        "WorkerDelegation",
        back_populates="to_worker",
        cascade="all, delete-orphan",
        foreign_keys="WorkerDelegation.to_worker_id",
    )


class WorkerOnboarding(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_onboarding"
    __table_args__ = (
        Index("ix_worker_onboarding_status", "onboarding_status"),
        Index("ix_worker_onboarding_ready_at", "ready_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, unique=True, index=True)
    knowledge_categories_required = Column(JSON, default=list)
    knowledge_coverage_score = Column(Float, nullable=False, default=0.0)
    knowledge_gaps = Column(JSON, default=list)
    connector_checks = Column(JSON, default=list)
    channels_verified = Column(JSON, default=list)
    initial_autonomy_level = Column(String(20), nullable=False, default="supervised")
    warmup_period_hours = Column(Integer, nullable=False, default=24)
    onboarding_status = Column(String(20), nullable=False, default="pending")
    ready_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="onboarding")


class WorkerRuntimeState(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_runtime_state"
    __table_args__ = (
        Index("ix_worker_runtime_status", "status"),
        Index("ix_worker_runtime_heartbeat", "last_heartbeat"),
        Index("ix_worker_runtime_priority", "current_priority"),
    )

    worker_id = Column(String(36), ForeignKey("agent_workers.id"), primary_key=True)
    current_incident_id = Column(String(36), nullable=True, index=True)
    current_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    current_priority = Column(String(20), nullable=False, default="idle")
    active_tasks_count = Column(Integer, nullable=False, default=0)
    max_parallel_tasks = Column(Integer, nullable=False, default=3)
    available_slots = Column(Integer, nullable=False, default=3)
    last_k8s_check = Column(DateTime, nullable=True)
    last_cost_check = Column(DateTime, nullable=True)
    last_jira_scan = Column(DateTime, nullable=True)
    system_health_summary = Column(JSON, default=dict)
    tasks_completed_today = Column(Integer, nullable=False, default=0)
    incidents_resolved_today = Column(Integer, nullable=False, default=0)
    escalations_today = Column(Integer, nullable=False, default=0)
    llm_cost_today = Column(Numeric(10, 4), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="active")
    last_heartbeat = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="runtime_state")
    current_session = relationship("Session")


class WorkerMonitor(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_monitors"
    __table_args__ = (
        Index("ix_worker_monitors_worker_active", "worker_id", "is_active"),
        Index("ix_worker_monitors_type", "monitor_type"),
        Index("ix_worker_monitors_last_check", "last_check_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    monitor_type = Column(String(50), nullable=False, index=True)
    check_interval_minutes = Column(Integer, nullable=False, default=15)
    check_query = Column(Text, nullable=True)
    threshold_config = Column(JSON, default=dict)
    action_on_warning = Column(String(50), nullable=True)
    action_on_critical = Column(String(50), nullable=True)
    baseline_json = Column(JSON, default=dict)
    last_check_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), nullable=True, index=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="monitors")
    events = relationship("WorkerMonitorEvent", back_populates="monitor", cascade="all, delete-orphan")


class WorkerMonitorEvent(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_monitor_events"
    __table_args__ = (
        Index("ix_worker_monitor_events_worker_created", "worker_id", "created_at"),
        Index("ix_worker_monitor_events_monitor_created", "monitor_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    monitor_id = Column(String(36), ForeignKey("worker_monitors.id"), nullable=False, index=True)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    severity = Column(String(20), nullable=False)
    detected_value = Column(Text, nullable=True)
    threshold_value = Column(Text, nullable=True)
    triggered_action = Column(String(50), nullable=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=True, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    monitor = relationship("WorkerMonitor", back_populates="events")
    worker = relationship("AgentWorker")
    session = relationship("Session")
    task_run = relationship("TaskRun")


class WorkerTrustEvent(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_trust_events"
    __table_args__ = (
        Index("ix_worker_trust_events_worker_created", "worker_id", "created_at"),
        Index("ix_worker_trust_events_type", "event_type"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=True, index=True)
    trust_delta = Column(Float, nullable=False, default=0.0)
    new_trust_score = Column(Float, nullable=False, default=0.5)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="trust_events")
    task_run = relationship("TaskRun")


class WorkerShift(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_shifts"
    __table_args__ = (
        Index("ix_worker_shifts_worker_status", "worker_id", "status"),
        Index("ix_worker_shifts_worker_start", "worker_id", "shift_start"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    shift_start = Column(DateTime, nullable=False, default=utc_now, index=True)
    shift_end = Column(DateTime, nullable=True, index=True)
    shift_type = Column(String(20), nullable=False, default="morning")
    handover_summary = Column(Text, nullable=True)
    open_items = Column(JSON, default=list)
    completed_items = Column(JSON, default=list)
    escalations_count = Column(Integer, nullable=False, default=0)
    autonomous_actions_count = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="active", index=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="shifts")


class WorkerDailyAgenda(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_daily_agenda"
    __table_args__ = (
        Index("ix_worker_daily_agenda_worker_date", "worker_id", "date", unique=True),
        Index("ix_worker_daily_agenda_status", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    agenda_items = Column(JSON, default=list)
    generated_at = Column(DateTime, default=utc_now, index=True)
    status = Column(String(20), nullable=False, default="pending")

    worker = relationship("AgentWorker", back_populates="daily_agendas")


class WorkerDelegation(WorkspaceBound, Base):
    __tablename__ = "worker_delegations"
    __table_args__ = (
        Index("ix_worker_delegations_from_created", "from_worker_id", "created_at"),
        Index("ix_worker_delegations_to_status", "to_worker_id", "status"),
        Index("ix_worker_delegations_project_status", "project_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    from_worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    to_worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    source_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    delegated_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    task_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=True, index=True)
    required_domain = Column(String(50), nullable=True, index=True)
    priority = Column(Integer, nullable=False, default=5)
    requested_action = Column(String(50), nullable=False, default="diagnose")
    context_summary = Column(Text, nullable=True)
    context_payload = Column(JSON, default=dict)
    auto_selected = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    response_note = Column(Text, nullable=True)
    completion_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    responded_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("Project")
    from_worker = relationship("AgentWorker", foreign_keys=[from_worker_id], back_populates="outgoing_delegations")
    to_worker = relationship("AgentWorker", foreign_keys=[to_worker_id], back_populates="incoming_delegations")
    source_session = relationship("Session", foreign_keys=[source_session_id])
    delegated_session = relationship("Session", foreign_keys=[delegated_session_id])
    task_run = relationship("TaskRun")


class WorkerEscalationRule(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_escalation_rules"
    __table_args__ = (
        Index("ix_worker_escalation_rules_worker", "worker_id"),
        Index("ix_worker_escalation_rules_priority", "priority"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    trigger_condition = Column(String(200), nullable=False)
    situation_pattern = Column(Text, nullable=True)
    escalate_to_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    escalate_via = Column(String(50), nullable=False, default="slack")
    message_template = Column(Text, nullable=True)
    priority = Column(String(20), nullable=False, default="medium")
    times_triggered = Column(Integer, nullable=False, default=0)
    times_resolved_after = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="escalation_rules")
    escalate_to_user = relationship("User")


class WorkerEscalation(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_escalations"
    __table_args__ = (
        Index("ix_worker_escalations_worker_created", "worker_id", "created_at"),
        Index("ix_worker_escalations_rule", "rule_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    rule_id = Column(String(36), ForeignKey("worker_escalation_rules.id"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    reason = Column(Text, nullable=False)
    context_summary = Column(Text, nullable=True)
    escalated_to = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    escalation_channel = Column(String(50), nullable=True)
    human_response = Column(Text, nullable=True)
    was_necessary = Column(Boolean, nullable=True)
    resolution_time_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="escalations")
    rule = relationship("WorkerEscalationRule")
    session = relationship("Session")
    escalated_to_user = relationship("User", foreign_keys=[escalated_to])


class WorkerReport(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_reports"
    __table_args__ = (Index("ix_worker_reports_worker_period", "worker_id", "period_start"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    report_type = Column(String(30), nullable=False, index=True)
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False)
    summary = Column(Text, nullable=True)
    incidents_detected = Column(Integer, nullable=False, default=0)
    incidents_resolved = Column(Integer, nullable=False, default=0)
    incidents_escalated = Column(Integer, nullable=False, default=0)
    autonomous_actions_taken = Column(Integer, nullable=False, default=0)
    knowledge_entries_created = Column(Integer, nullable=False, default=0)
    memory_updates = Column(Integer, nullable=False, default=0)
    highlights = Column(JSON, default=list)
    concerns = Column(JSON, default=list)
    recommendations = Column(JSON, default=list)
    delivery_status = Column(String(20), nullable=False, default="pending", index=True)
    delivered_to = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="reports")


class WorkerLearning(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"worker_id": "agent_workers"}
    __tablename__ = "worker_learnings"
    __table_args__ = (Index("ix_worker_learnings_worker_created", "worker_id", "created_at"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    worker_id = Column(String(36), ForeignKey("agent_workers.id"), nullable=False, index=True)
    learning_type = Column(String(50), nullable=False, index=True)
    context = Column(Text, nullable=True)
    learning_content = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    times_applied = Column(Integer, nullable=False, default=0)
    times_succeeded = Column(Integer, nullable=False, default=0)
    source_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    worker = relationship("AgentWorker", back_populates="learnings")
    source_session = relationship("Session")
