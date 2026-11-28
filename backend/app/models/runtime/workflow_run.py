"""A workflow run: the server-side state of one workflow execution."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import validates

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class WorkflowRun(WorkspaceBound, Base):
    __workspace_owners__ = {"work_item_id": "work_items"}
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_status", "status", "updated_at"),
        Index("ix_workflow_runs_work_item", "work_item_id"),
        Index("ix_workflow_runs_requested_by", "requested_by", "status"),
        Index("ix_workflow_runs_parent", "parent_run_id"),
        Index("ix_workflow_runs_responsible", "responsible_user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    # phased: a flow version of kind "phased"
    workflow_kind = Column(String(20), nullable=False)
    workflow_key = Column(String(180), nullable=False)
    title = Column(String(220), nullable=False, default="")
    flow_definition_version_id = Column(String(36), ForeignKey("flow_definition_versions.id"), nullable=True)
    workflow_version = Column(String(40), nullable=False, default="")
    work_item_id = Column(String(36), ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    ticket_key = Column(String(220), nullable=True)
    repository = Column(String(500), nullable=True)
    branch = Column(String(500), nullable=True)
    pull_request = Column(JSON, nullable=False, default=dict)
    # Cursor and state: running | waiting | paused | completed | stopped | failed
    status = Column(String(20), nullable=False, default="running")
    waiting_kind = Column(String(40), nullable=True)
    pause_reason = Column(String(40), nullable=True)
    current_node_id = Column(String(128), nullable=True)
    node_state = Column(JSON, nullable=False, default=dict)
    loop_counters = Column(JSON, nullable=False, default=dict)
    limits = Column(JSON, nullable=False, default=dict)
    budget_usage = Column(JSON, nullable=False, default=dict)
    gate_results = Column(JSON, nullable=False, default=dict)
    context = Column(JSON, nullable=False, default=dict)
    outcome = Column(String(40), nullable=True)
    last_error = Column(Text, nullable=True)
    parent_run_id = Column(String(36), ForeignKey("workflow_runs.id"), nullable=True)
    parent_node_id = Column(String(128), nullable=True)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    # The responsible person: who the run's decisions go to, besides today's rights.
    # ``responsible_source``: requester | reporter | assignee | taken_over | accepted (``workflow_runs.responsible``).
    # None: nobody was resolved (the broadcast case); the existing decision audience applies.
    responsible_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responsible_source = Column(String(20), nullable=True)
    # Compare-and-set counter: every state change first claims the row (``records.lock_run``).
    state_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class WorkflowRunSession(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"run_id": "workflow_runs"}
    __tablename__ = "workflow_run_sessions"
    __table_args__ = (
        Index("ix_workflow_run_sessions_session", "session_id", "active"),
        Index("ix_workflow_run_sessions_run", "run_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    # main | child | reviewer
    role = Column(String(20), nullable=False, default="main")
    # chat | octryx_claude
    runtime = Column(String(20), nullable=False, default="chat")
    active = Column(Boolean, nullable=False, default=True)
    linked_at = Column(DateTime, default=utc_now, nullable=False)


class WorkflowRunEvent(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"run_id": "workflow_runs"}
    __tablename__ = "workflow_run_events"
    # ``kind``/``created_at``: a worker reads one kind of event since its cursor (the PR review bot's instant
    # trigger, ``pr_review_bot.instant``) without scanning the history.
    __table_args__ = (Index("ix_workflow_run_events_run", "run_id", "created_at"),
                      Index("ix_workflow_run_events_kind", "kind", "created_at"))

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(40), nullable=False)
    node_id = Column(String(128), nullable=True)
    detail = Column(JSON, nullable=False, default=dict)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    @validates("detail")
    def _masked_detail(self, _key: str, value: Any) -> Any:
        # An event can carry a platform action's arguments or result text, so it is stored masked.
        from ...services.secret_masking import masked

        return masked(value) if value else value


class WorkflowRunDecision(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"run_id": "workflow_runs"}
    __tablename__ = "workflow_run_decisions"
    __table_args__ = (Index("ix_workflow_run_decisions_run", "run_id", "created_at"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String(128), nullable=True)
    # confirmation | approval | pause
    kind = Column(String(20), nullable=False)
    # the confirmation's payload kind (test_contract, ticket_draft, ...) or the pause reason
    subject = Column(String(40), nullable=False, default="")
    action = Column(String(20), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    payload_hash = Column(String(71), nullable=False, default="")
    approval_id = Column(String(36), ForeignKey("approvals.id"), nullable=True)
    decided_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
