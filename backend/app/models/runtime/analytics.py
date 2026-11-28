import uuid

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now
from ..json_text import dump_json_dict, safe_json_dict


def uuid_pk() -> str:
    return str(uuid.uuid4())


class AnalyticsDaily(WorkspaceBound, Base):
    __tablename__ = "analytics_daily"
    # One row per scope and day.
    __table_args__ = (Index("ix_analytics_daily_scope_date", "project_id", "team_id", "date", unique=True),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True)
    team_id = Column(String(36), ForeignKey("teams.id"), nullable=True, index=True)
    date = Column(Date, nullable=False, index=True)
    sessions_total = Column(Integer, default=0)
    sessions_completed = Column(Integer, default=0)
    sessions_failed = Column(Integer, default=0)
    avg_session_duration_minutes = Column(Float, nullable=True)
    tool_calls_total = Column(Integer, default=0)
    tool_calls_success = Column(Integer, default=0)
    tool_calls_failed = Column(Integer, default=0)
    approvals_requested = Column(Integer, default=0)
    approvals_approved = Column(Integer, default=0)
    total_cost = Column(Numeric(10, 4), default=0)
    cost_by_provider_json = Column(Text, default="{}")
    total_tokens_in = Column(Integer, default=0)
    total_tokens_out = Column(Integer, default=0)
    knowledge_queries = Column(Integer, default=0)
    knowledge_hits = Column(Integer, default=0)
    memory_reads = Column(Integer, default=0)
    memory_writes = Column(Integer, default=0)
    positive_feedback = Column(Integer, default=0)
    negative_feedback = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    project = relationship("Project")
    team = relationship("Team")

    @property
    def cost_by_provider(self) -> dict[str, float]:
        payload = safe_json_dict(self.cost_by_provider_json)
        return {str(key): float(value or 0.0) for key, value in payload.items()}

    @cost_by_provider.setter
    def cost_by_provider(self, value: dict[str, float] | None) -> None:
        payload = {str(key): float(amount or 0.0) for key, amount in (value or {}).items()}
        self.cost_by_provider_json = dump_json_dict(payload)


class ReportExport(Base):
    __tablename__ = "report_exports"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    report_type = Column(String(50), nullable=False)
    parameters_json = Column(Text, default="{}")
    format = Column(String(10), default="json")
    status = Column(String(20), default="pending", index=True)
    file_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    completed_at = Column(DateTime, nullable=True)

    creator = relationship("User")

    @property
    def parameters(self) -> dict:
        return safe_json_dict(self.parameters_json)

    @parameters.setter
    def parameters(self, value: dict | None) -> None:
        self.parameters_json = dump_json_dict(value or {})
