import json
import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now
from ..json_text import safe_json_dict, safe_json_list


def uuid_pk():
    return str(uuid.uuid4())


# The closed ``tasks.dispatch_binding`` values, required on every Action
# (runtime seams: scheduler/dispatch/agent_definition_binding.py; save rules: services/admin/task/_dispatch_binding.py).
TASK_DEFINITION_BINDING = "task_definition"  # runs its own steps, Work intake type or prompt (Worker or local)
AGENT_DEFINITION_BINDING = "agent_definition"  # runs its selected AgentDefinition directly
WORKFLOW_RUN_BINDING = "workflow_run"  # starts a phased workflow run
DISPATCH_BINDINGS = (TASK_DEFINITION_BINDING, AGENT_DEFINITION_BINDING, WORKFLOW_RUN_BINDING)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # Closed, explicitly authored dispatch binding (scheduler/dispatch/agent_definition_binding.py).
        CheckConstraint(
            "dispatch_binding IN (" + ", ".join(f"'{value}'" for value in DISPATCH_BINDINGS) + ")",
            name="ck_tasks_dispatch_binding"
        ),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    task_type = Column(String(100), nullable=False, default="agent_run")
    agent_type = Column(String(50), default="diagnosis")
    # A cron set on the Action itself; the scheduler registers it next to the Action's Scheduler rows.
    schedule = Column(String(100), nullable=True)
    config = Column(JSON, default=dict)
    max_concurrent_agents = Column(Integer, default=3)
    default_runtime_selector_json = Column(Text, default="{}")
    is_active = Column(Boolean, default=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True)
    dispatch_binding = Column(String(32), nullable=False)

    project = relationship("Project", back_populates="tasks")
    owner = relationship("User")
    runs = relationship("TaskRun", back_populates="task", cascade="all, delete-orphan")
    steps = relationship(
        "TaskStep",
        back_populates="task",
        order_by="TaskStep.position",
        cascade="all, delete-orphan",
    )

    @property
    def default_runtime_selector(self) -> dict:
        return safe_json_dict(self.default_runtime_selector_json)

    @default_runtime_selector.setter
    def default_runtime_selector(self, value: dict):
        self.default_runtime_selector_json = json.dumps(value or {})


class TaskStep(Base):
    __tablename__ = "task_steps"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=1)
    name = Column(String(200), nullable=False, default="Step")
    step_type = Column(String(50), default="analysis")
    # connector_fetch fields
    connector = Column(String(50), nullable=True)
    connector_action = Column(String(100), nullable=True)
    connector_params_json = Column(Text, default="{}")
    # agent / instructions
    instructions = Column(Text, default="")
    runtime_selector_json = Column(Text, default="{}")
    context_fields_json = Column(Text, default="[]")
    allowed_tools_json = Column(Text, default="[]")
    # sub_agent_spawn
    spawn_strategy = Column(String(50), default="per_item")
    spawn_count = Column(Integer, nullable=True)
    # verification
    max_fix_attempts = Column(Integer, default=2)
    # condition (branching)
    condition_expr = Column(Text, nullable=True)
    condition_true_step = Column(Integer, nullable=True)
    condition_false_step = Column(Integer, nullable=True)
    # general
    agent_timeout_seconds = Column(Integer, default=300)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    task = relationship("Task", back_populates="steps")

    @property
    def runtime_selector(self) -> dict:
        return safe_json_dict(self.runtime_selector_json)

    @runtime_selector.setter
    def runtime_selector(self, value: dict):
        self.runtime_selector_json = json.dumps(value or {})

    @property
    def context_fields(self) -> list[str]:
        return [str(item) for item in safe_json_list(self.context_fields_json)]

    @property
    def allowed_tools(self) -> list[str]:
        return [str(item) for item in safe_json_list(self.allowed_tools_json)]

    @property
    def connector_params(self) -> dict:
        return safe_json_dict(self.connector_params_json)


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (
        # Hot reads: the dispatcher's wait estimate (latest completed), a task's latest run,
        # runs by status in a time window, and a session's runs.
        Index("ix_task_runs_completed_at", "completed_at"),
        Index("ix_task_runs_task_started", "task_id", "started_at"),
        Index("ix_task_runs_status_started", "status", "started_at"),
        Index("ix_task_runs_session_id", "session_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    parent_run_id = Column(String(36), ForeignKey("task_runs.id"), nullable=True)
    trigger_type = Column(String(50), default="manual")  # manual | schedule | scheduler | retry | webhook
    trigger_id = Column(String(36), nullable=True)  # scheduler_id, failed_task_run_id, or webhook_id
    status = Column(String(50), default="pending", index=True)
    started_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    input_ = Column("input", JSON, default=dict)
    output = Column(JSON, nullable=True)
    steps_log_json = Column(Text, default="[]")  # [{step_id, name, status, output, fix_attempts}]
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)
    # The platform process boot that executes a locally claimed run (runtime_ownership); NULL for a remote worker.
    owner_process_id = Column(String(36), nullable=True)

    task = relationship("Task", back_populates="runs")
    session = relationship("Session")
    started_by_user = relationship("User")
    sub_runs = relationship("TaskRun", foreign_keys=[parent_run_id])
    queue_entry = relationship("TaskQueueEntry", uselist=False, back_populates="task_run", cascade="all, delete-orphan")

    @property
    def steps_log(self) -> list[dict]:
        return [item for item in safe_json_list(self.steps_log_json) if isinstance(item, dict)]

    @steps_log.setter
    def steps_log(self, value: list[dict]):
        self.steps_log_json = json.dumps(value or [])
