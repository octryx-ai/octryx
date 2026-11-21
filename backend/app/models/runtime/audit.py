import uuid
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import relationship, validates

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        # A person's records of one action since a time (attention dismissals, problem
        # acknowledgements), and the latest record of one action for one resource (knowledge settings state).
        Index("ix_audit_log_user_action_created", "user_id", "action", "created_at"),
        Index("ix_audit_log_action_resource_created", "action", "resource_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    action = Column(String(200), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(String(200))
    details = Column(JSON, default=dict)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=utc_now, index=True)

    user = relationship("User")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey("messages.id"), nullable=True)
    tool_name = Column(String(200), nullable=False)
    parameters = Column(JSON, default=dict)
    result = Column(JSON, nullable=True)
    status = Column(String(50), default="success")
    duration_ms = Column(Integer, nullable=True)
    request_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now)

    session = relationship("Session")

    @validates("parameters")
    def _masked_parameters(self, _key: str, value: Any) -> Any:
        """Stored masked like transcripts: a model writes secrets into arguments (e.g. an sk- token in a body).
        The tool already ran with the real arguments; this row is the audit and the UI's view of them."""
        from ...services.secret_masking import masked

        return masked(value) if value else value

    @validates("result")
    def _masked_result(self, _key: str, value: Any) -> Any:
        """A result can echo what the call sent (e.g. a REST result carrying the body's token); stored
        masked like the parameters. The model already got the result without the call's own secrets (registry)."""
        from ...services.secret_masking import masked

        return masked(value) if value else value


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        # Usage queries filter by time window, per session (and Workspace via sessions) and per user.
        Index("ix_usage_events_created_at", "created_at"),
        Index("ix_usage_events_session_created", "session_id", "created_at"),
        Index("ix_usage_events_user_created", "user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    provider = Column(String(100))
    model = Column(String(100))
    tokens_in = Column(BigInteger, default=0)
    tokens_out = Column(BigInteger, default=0)
    cache_read_tokens = Column(BigInteger, nullable=True)
    cache_creation_tokens = Column(BigInteger, nullable=True)
    cost = Column(Numeric(10, 6), default=0)
    # A seat call's API equivalent at the list price (``budget/api_equivalent``): shown apart from ``cost``, never
    # added to it. NULL for a non-seat call or a model without a list price.
    list_cost = Column(Numeric(12, 6), nullable=True)
    # How this event's cost was established. ``cost_source`` is the governed
    # contract the turn ran under (NULL for ungoverned providers) and
    # ``cost_status`` is the accounting outcome, so a zero cost is auditable
    # instead of ambiguous.
    cost_source = Column(String(32), nullable=True)
    cost_status = Column(String(64), nullable=True)
    request_id = Column(String(64), nullable=True, index=True)
    # The registered provider-dispatch owner (services/model_gateway/dispatch_owners.py)
    # whose governed call this event accounts; NULL for events without one.
    dispatch_owner = Column(String(64), nullable=True, index=True)
    # Attribution dimensions for quota scoping
    agent_chain_id = Column(String(36), nullable=True, index=True)
    flow_definition_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime, default=utc_now)

    session = relationship("Session")
    user = relationship("User")


class TurnTrace(Base):
    __tablename__ = "turn_traces"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey("messages.id"), nullable=True, index=True)
    provider = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    input_messages_json = Column(JSON, default=list)
    context_snapshot_json = Column(JSON, default=dict)
    tool_trace_json = Column(JSON, default=list)
    raw_output = Column(JSON, default=dict)
    usage_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)

    session = relationship("Session")


class TurnTraceSummary(Base):
    """The run summary of one ``turn_traces`` row (``services/observability/run_summary.py``).

    Runs groups and filters on these columns and never aggregates the trace JSON. A table of its own, because
    ``turn_traces`` is frozen by the adoption revisions (a startup ``create_all`` must keep matching them).
    """

    __tablename__ = "turn_trace_summaries"

    trace_id = Column(String(36), ForeignKey("turn_traces.id", ondelete="CASCADE"), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    run_key = Column(String(120), nullable=False, index=True)
    outcome = Column(String(32), nullable=False)
    started_at = Column(DateTime, nullable=True)
    agent_label = Column(String(200), nullable=True)
    provider = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)


class ThreadContext(Base):
    __tablename__ = "thread_context"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False, index=True, unique=True)
    version = Column(Integer, default=1, nullable=False)
    context_json = Column(JSON, default=dict)
    derived_from_message_id = Column(String(36), ForeignKey("messages.id"), nullable=True, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    session = relationship("Session")
