import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

RESET_PERIOD_DAILY = "daily"
RESET_PERIOD_WEEKLY = "weekly"
RESET_PERIOD_MONTHLY = "monthly"
RESET_PERIOD_NEVER = "never"
ALL_RESET_PERIODS = frozenset({RESET_PERIOD_DAILY, RESET_PERIOD_WEEKLY, RESET_PERIOD_MONTHLY, RESET_PERIOD_NEVER})


def uuid_pk() -> str:
    return str(uuid.uuid4())


class BudgetPolicy(WorkspaceBound, Base):
    """Budget / quota policy. At least one scope dimension is set; limits apply per ``reset_period``, each with its own
    request, token and cost columns."""

    __tablename__ = "budget_policies"
    __table_args__ = (
        Index("ix_budget_policies_user_project", "user_id", "project_id"),
        Index("ix_budget_policies_is_active", "is_active"),
        Index("ix_budget_policies_agent_chain", "agent_chain_id"),
        Index("ix_budget_policies_flow", "flow_definition_id"),
        Index("ix_budget_policies_provider", "provider_id"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(200), nullable=False)

    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=True, index=True)
    # Soft-string refs (no FK constraint) to avoid circular dependencies
    agent_chain_id = Column(String(36), nullable=True)
    flow_definition_id = Column(String(36), nullable=True)
    # FK to llm_providers; if set, policy applies only to that provider
    provider_id = Column(String(36), ForeignKey("llm_providers.id"), nullable=True)
    domain_pack_id = Column(String(36), nullable=True)

    reset_period = Column(String(20), nullable=False, default=RESET_PERIOD_DAILY)

    # Daily limits, also the limits of reset_period "never".
    daily_request_limit = Column(Integer, nullable=True)
    daily_token_limit = Column(Integer, nullable=True)
    daily_cost_limit = Column(Numeric(12, 6), nullable=True)

    weekly_request_limit = Column(Integer, nullable=True)
    weekly_token_limit = Column(Integer, nullable=True)
    weekly_cost_limit = Column(Numeric(12, 6), nullable=True)

    monthly_request_limit = Column(Integer, nullable=True)
    monthly_token_limit = Column(Integer, nullable=True)
    monthly_cost_limit = Column(Numeric(12, 6), nullable=True)

    warn_at_percent = Column(Integer, nullable=False, default=80)
    block_at_percent = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    user = relationship("User")
    project = relationship("Project")


class BudgetAlert(WorkspaceBound, Base):
    __workspace_owners__ = {"session_id": "sessions"}
    __tablename__ = "budget_alerts"
    __table_args__ = (Index("ix_budget_alerts_policy_metric", "policy_id", "metric_name", "threshold_level"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    policy_id = Column(String(36), ForeignKey("budget_policies.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True, index=True)
    metric_name = Column(String(40), nullable=False)
    threshold_level = Column(String(20), nullable=False)
    current_value = Column(Numeric(14, 6), nullable=False, default=0)
    limit_value = Column(Numeric(14, 6), nullable=False, default=0)
    percent_used = Column(Integer, nullable=False, default=0)
    details = Column(JSON, default=dict)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    policy = relationship("BudgetPolicy")
    user = relationship("User")
    project = relationship("Project")
    session = relationship("Session")
