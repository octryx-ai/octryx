from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class OrchestratorAgentRun(Base):
    """Records a top-level orchestrator run that coordinates child agent sessions.

    This model is the authoritative record for supervisor, sequential, parallel,
    reviewer/critic, and evaluator-optimizer orchestration patterns. It tracks the
    pattern type, parent-child relationships, and per-step delegation metadata so
    that the full handoff graph is visible in traces and audits.

    Pattern responsibilities:

    * **supervisor** — the orchestrator plans, delegates to children, monitors
      results, merges outputs, resolves conflicts, escalates on failure, and closes.
    * **sequential** — children run one after another in edge order; each child's
      output feeds the next.
    * **parallel** — children run concurrently; the supervisor waits for all
      before merging.  (See also SubAgentGroup for the child-session lifecycle.)
    * **reviewer_critic** — a reviewer agent scores the primary agent's output;
      on failure the primary revises and re-submits.
    * **evaluator_optimizer** — an evaluator scores the output; on failure the
      agent revises until the score passes or max_iterations is reached.
    """

    __tablename__ = "orchestrator_agent_runs"
    __table_args__ = (
        Index("ix_orchestrator_runs_session_id", "session_id"),
        Index("ix_orchestrator_runs_parent_session", "parent_session_id"),
        Index("ix_orchestrator_runs_pattern", "pattern_type"),
        Index("ix_orchestrator_runs_status", "status"),
        Index("ix_orchestrator_runs_created_at", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)

    # Core identity
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    parent_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)

    # Orchestration identity
    pattern_type = Column(
        String(32),
        nullable=False,
        index=True,
        # single | supervisor | sequential | parallel | reviewer_critic | evaluator_optimizer
    )
    agent_definition_id = Column(String(36), ForeignKey("agent_definitions.id"), nullable=True)
    flow_definition_version_id = Column(String(36), ForeignKey("flow_definition_versions.id"), nullable=True)
    flow_node_id = Column(String(128), nullable=True)  # id of the node within the flow that triggered this run

    # Step tracking — current delegation index and total steps
    current_step_index = Column(Integer, nullable=False, default=0)
    total_steps = Column(Integer, nullable=False, default=1)

    # Child tracking — IDs of all directly delegated child sessions in order
    child_session_ids_json = Column(JSON, nullable=False, default=list)

    # Merge / conflict resolution record
    merged_output_json = Column(JSON, nullable=False, default=dict)
    conflict_resolutions_json = Column(JSON, nullable=False, default=list)

    # Reviewer/critic / evaluator state
    reviewer_session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    last_review_score = Column(String(16), nullable=True)  # pass | fail | score float
    last_review_notes = Column(Text, nullable=True)
    revision_count = Column(Integer, nullable=False, default=0)
    max_iterations = Column(Integer, nullable=False, default=3)

    # Routing context for the orchestrator
    routing_policy_json = Column(JSON, nullable=False, default=dict)
    delegation_policy_json = Column(JSON, nullable=False, default=dict)

    # Runtime state
    status = Column(
        String(32),
        nullable=False,
        default="running",
        # running | waiting_children | waiting_review | paused | completed | failed | cancelled
        index=True,
    )
    last_child_id = Column(String(36), nullable=True)
    last_error = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships — child sessions are accessed via child_session_ids_json + DB queries
    # rather than a direct ORM relationship to avoid circular import issues with Session
    session = relationship("Session", foreign_keys=[session_id])
    parent_session = relationship("Session", foreign_keys=[parent_session_id])
    project = relationship("Project")
    agent_definition = relationship("AgentDefinition")
    flow_definition_version = relationship("FlowDefinitionVersion")
    reviewer_session = relationship("Session", foreign_keys=[reviewer_session_id])


# ---------------------------------------------------------------------------
# Pattern constants (mirrored from the service layer)
# ---------------------------------------------------------------------------

ORCHESTRATOR_PATTERN_SINGLE = "single"
ORCHESTRATOR_PATTERN_SUPERVISOR = "supervisor"
ORCHESTRATOR_PATTERN_SEQUENTIAL = "sequential"
ORCHESTRATOR_PATTERN_PARALLEL = "parallel"
ORCHESTRATOR_PATTERN_REVIEWER_CRITIC = "reviewer_critic"
ORCHESTRATOR_PATTERN_EVALUATOR_OPTIMIZER = "evaluator_optimizer"
ORCHESTRATOR_PATTERNS = {
    ORCHESTRATOR_PATTERN_SINGLE,
    ORCHESTRATOR_PATTERN_SUPERVISOR,
    ORCHESTRATOR_PATTERN_SEQUENTIAL,
    ORCHESTRATOR_PATTERN_PARALLEL,
    ORCHESTRATOR_PATTERN_REVIEWER_CRITIC,
    ORCHESTRATOR_PATTERN_EVALUATOR_OPTIMIZER,
}
ORCHESTRATOR_STATUS_RUNNING = "running"
ORCHESTRATOR_STATUS_WAITING_CHILDREN = "waiting_children"
ORCHESTRATOR_STATUS_WAITING_REVIEW = "waiting_review"
ORCHESTRATOR_STATUS_PAUSED = "paused"
ORCHESTRATOR_STATUS_COMPLETED = "completed"
ORCHESTRATOR_STATUS_FAILED = "failed"
ORCHESTRATOR_STATUS_CANCELLED = "cancelled"
ORCHESTRATOR_STATUSES = {
    ORCHESTRATOR_STATUS_RUNNING,
    ORCHESTRATOR_STATUS_WAITING_CHILDREN,
    ORCHESTRATOR_STATUS_WAITING_REVIEW,
    ORCHESTRATOR_STATUS_PAUSED,
    ORCHESTRATOR_STATUS_COMPLETED,
    ORCHESTRATOR_STATUS_FAILED,
    ORCHESTRATOR_STATUS_CANCELLED,
}
