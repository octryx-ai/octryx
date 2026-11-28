"""Product Run and Product Run Attempt records and their append-only transitions."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

RUN_STATE_REQUESTED = "requested"
RUN_STATE_ADMITTED = "admitted"
RUN_STATE_RUNNING = "running"
RUN_STATE_VERIFYING = "verifying"
RUN_STATE_COMPLETED = "completed"
RUN_STATE_FINISHED_UNVERIFIED = "finished_unverified"
RUN_STATE_FAILED = "failed"
RUN_STATE_CANCELLED = "cancelled"
RUN_STATE_DENIED = "denied"
RUN_STATE_NEEDS_APPROVAL = "needs_approval"
RUN_STATE_NEEDS_CONFIGURATION = "needs_configuration"
RUN_STATE_NEEDS_CLARIFICATION = "needs_clarification"
RUN_STATE_WAITING_APPROVAL = "waiting_approval"
RUN_STATE_INCOMPLETE = "incomplete"

RUN_STATES: tuple[str, ...] = (
    RUN_STATE_REQUESTED,
    RUN_STATE_ADMITTED,
    RUN_STATE_RUNNING,
    RUN_STATE_VERIFYING,
    RUN_STATE_COMPLETED,
    RUN_STATE_FINISHED_UNVERIFIED,
    RUN_STATE_FAILED,
    RUN_STATE_CANCELLED,
    RUN_STATE_DENIED,
    RUN_STATE_NEEDS_APPROVAL,
    RUN_STATE_NEEDS_CONFIGURATION,
    RUN_STATE_NEEDS_CLARIFICATION,
    RUN_STATE_WAITING_APPROVAL,
    RUN_STATE_INCOMPLETE,
)

RUN_END_REASONS: tuple[str, ...] = (
    "gate_denied",
    "gate_missing_profile",
    "gate_unknown_status",
    "gate_needs_approval",
    "gate_needs_configuration",
    "gate_needs_clarification",
    "runtime_not_ready",
    "model_alias_not_admitted",
    "model_data_policy_denied",
    "preparation_failed",
    "runtime_finished",
    "provider_error",
    "runtime_error",
    "runtime_exception",
    "approval_pending",
    "clarification_requested",
    "completion_not_accepted",
    "delegated_outcome_unrecorded",
    "generator_closed",
    "task_cancelled",
    # The owning process died (restart or crash) mid-turn.
    "interrupted_by_restart",
    # The execution gate held the turn for the user's workflow confirmation; the proposed
    # workflow waits on its governed approval record (``needs_approval`` family; appended last
    # because the parity test compares whole expressions).
    "awaiting_workflow_confirmation",
)

RUN_ORIGIN_CHAT_TURN = "chat_turn"
# A child turn of a sub-agent group, and a turn the scheduler runs for a task.
RUN_ORIGIN_SUB_AGENT = "sub_agent"
RUN_ORIGIN_SCHEDULED_TASK = "scheduled_task"
RUN_ORIGINS: tuple[str, ...] = (RUN_ORIGIN_CHAT_TURN, RUN_ORIGIN_SUB_AGENT, RUN_ORIGIN_SCHEDULED_TASK)

RUN_WORKSPACE_SOURCE_SESSION_PROJECT = "session_project"
RUN_WORKSPACE_SOURCES: tuple[str, ...] = (RUN_WORKSPACE_SOURCE_SESSION_PROJECT,)

TRANSITION_ACTOR_RUNTIME = "runtime"
TRANSITION_ACTOR_SYSTEM = "system"
TRANSITION_ACTORS: tuple[str, ...] = (TRANSITION_ACTOR_RUNTIME, TRANSITION_ACTOR_SYSTEM)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _nullable_in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR {_in_list(column, values)}"


def uuid_pk() -> str:
    return str(uuid.uuid4())


class ProductRun(WorkspaceBound, Base):
    """One governed unit of product work in exactly one Workspace."""
    __workspace_column__ = "workspace_id"

    __tablename__ = "product_runs"
    __table_args__ = (
        CheckConstraint(_in_list("state", RUN_STATES), name="ck_product_runs_state"),
        CheckConstraint(_nullable_in_list("end_reason", RUN_END_REASONS), name="ck_product_runs_end_reason"),
        CheckConstraint(_in_list("origin", RUN_ORIGINS), name="ck_product_runs_origin"),
        CheckConstraint(
            _in_list("workspace_source", RUN_WORKSPACE_SOURCES),
            name="ck_product_runs_workspace_source",
        ),
        CheckConstraint("attempt_count >= 1", name="ck_product_runs_attempt_count"),
        CheckConstraint("version >= 1", name="ck_product_runs_version"),
        Index("ix_product_runs_workspace_created", "workspace_id", "created_at"),
        Index("ix_product_runs_owner_created", "owner_user_id", "created_at"),
        Index("ix_product_runs_session_created", "session_id", "created_at"),
        Index("ix_product_runs_state", "state"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    # No foreign key: a re-run deletes later messages, and the run must survive that.
    turn_user_message_id = Column(String(36), nullable=True)
    origin = Column(String(32), nullable=False)
    workspace_source = Column(String(32), nullable=False)
    state = Column(String(32), nullable=False)
    end_reason = Column(String(48), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
    ended_at = Column(DateTime, nullable=True)

    attempts = relationship(
        "ProductRunAttempt",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ProductRunAttempt.attempt_number.asc()",
    )


class ProductRunAttempt(WorkspaceBound, Base):
    """One execution of a Product Run."""
    __workspace_column__ = "workspace_id"

    __tablename__ = "product_run_attempts"
    __table_args__ = (
        CheckConstraint(_in_list("state", RUN_STATES), name="ck_product_run_attempts_state"),
        CheckConstraint(
            _nullable_in_list("end_reason", RUN_END_REASONS),
            name="ck_product_run_attempts_end_reason",
        ),
        CheckConstraint("attempt_number >= 1", name="ck_product_run_attempts_number"),
        CheckConstraint("version >= 1", name="ck_product_run_attempts_version"),
        Index("uq_product_run_attempts_run_number", "run_id", "attempt_number", unique=True),
        Index("ix_product_run_attempts_workspace", "workspace_id"),
        Index("ix_product_run_attempts_final_trace", "final_trace_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("product_runs.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    state = Column(String(32), nullable=False)
    end_reason = Column(String(48), nullable=True)
    # Safe tokens copied from the turn execution snapshot; validated by the service.
    gate_status = Column(String(32), nullable=True)
    gate_decision_source = Column(String(48), nullable=True)
    execution_profile_id = Column(String(160), nullable=True)
    # No foreign key: a re-run deletes later traces, and the attempt must survive that.
    final_trace_id = Column(String(36), nullable=True)
    # The platform process (``runtime_process_leases.id``) that last moved this Attempt
    # into an active state. No foreign key: expired leases are pruned, the Attempt stays.
    owner_process_id = Column(String(36), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    run = relationship("ProductRun", back_populates="attempts")


class ProductRunTransition(WorkspaceBound, Base):
    """Append-only audit of every Attempt state change."""
    __workspace_column__ = "workspace_id"

    __tablename__ = "product_run_transitions"
    __table_args__ = (
        CheckConstraint(
            _nullable_in_list("from_state", RUN_STATES),
            name="ck_product_run_transitions_from_state",
        ),
        CheckConstraint(_in_list("to_state", RUN_STATES), name="ck_product_run_transitions_to_state"),
        CheckConstraint(
            _nullable_in_list("end_reason", RUN_END_REASONS),
            name="ck_product_run_transitions_end_reason",
        ),
        CheckConstraint(_in_list("actor", TRANSITION_ACTORS), name="ck_product_run_transitions_actor"),
        CheckConstraint("sequence >= 1", name="ck_product_run_transitions_sequence"),
        Index("uq_product_run_transitions_run_sequence", "run_id", "sequence", unique=True),
        Index("ix_product_run_transitions_attempt", "attempt_id"),
        Index("ix_product_run_transitions_workspace_recorded", "workspace_id", "recorded_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("product_runs.id", ondelete="CASCADE"), nullable=False)
    attempt_id = Column(String(36), ForeignKey("product_run_attempts.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    sequence = Column(Integer, nullable=False)
    from_state = Column(String(32), nullable=True)
    to_state = Column(String(32), nullable=False)
    end_reason = Column(String(48), nullable=True)
    actor = Column(String(16), nullable=False)
    recorded_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = [
    "RUN_END_REASONS",
    "RUN_ORIGINS",
    "RUN_ORIGIN_CHAT_TURN",
    "RUN_ORIGIN_SCHEDULED_TASK",
    "RUN_ORIGIN_SUB_AGENT",
    "RUN_STATES",
    "RUN_WORKSPACE_SOURCES",
    "RUN_WORKSPACE_SOURCE_SESSION_PROJECT",
    "TRANSITION_ACTORS",
    "TRANSITION_ACTOR_RUNTIME",
    "TRANSITION_ACTOR_SYSTEM",
    "ProductRun",
    "ProductRunAttempt",
    "ProductRunTransition",
]
