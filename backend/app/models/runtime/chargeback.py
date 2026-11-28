import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now
from ..json_text import dump_json_dict, safe_json_dict


def uuid_pk() -> str:
    return str(uuid.uuid4())


class CostAllocationRule(WorkspaceBound, Base):
    __tablename__ = "cost_allocation_rules"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    cost_center = Column(String(120), nullable=False, index=True)
    percentage = Column(Numeric(7, 2), nullable=False, default=100)
    valid_from = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    project = relationship("Project")


class MonthlyCostReport(WorkspaceBound, Base):
    __tablename__ = "monthly_cost_reports"
    __table_args__ = (
        Index(
            "ix_monthly_cost_reports_period_project_provider",
            "period",
            "project_id",
            "provider_id",
            unique=True,
        ),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    period = Column(String(7), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    provider_id = Column(String(100), nullable=True, index=True)
    total_cost = Column(Numeric(12, 6), nullable=False, default=0)
    report_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=utc_now, index=True)

    project = relationship("Project")

    @property
    def report(self) -> dict:
        return safe_json_dict(self.report_json)

    @report.setter
    def report(self, value: dict | None) -> None:
        self.report_json = dump_json_dict(value or {})
