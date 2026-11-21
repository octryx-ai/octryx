"""Work item analyses: one governed analysis run of one Work Item version.

A row is written before the model run starts (``running``) and settled once (``succeeded``, ``failed``,
``needs_configuration`` or ``denied``). ``active_key`` (``<work item>:<item version>:<template>``) is set
while a run is ``running`` or ``succeeded`` and cleared on any other outcome; its unique constraint makes
"one analysis per item version" hold under a race too, while a failed run can be retried. The structured
analysis (``analysis_json``) is data written by an agent; the rendered note lives on the Work Item.

``runner`` says where the analysis ran: ``governed`` (the server's model run) or ``seat`` (the user's own seat
session, submitted through ``work_item_analysis_submit``; platform cost 0). ``model`` is the model that wrote
it, when known. ``error_detail`` is a short, sanitized cause of a failure (never a body or a secret).
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


class WorkItemAnalysis(Base):
    __tablename__ = "work_item_analysis"
    __table_args__ = (
        UniqueConstraint("active_key", name="uq_work_item_analysis_active_key"),
        Index("ix_work_item_analysis_item_created", "work_item_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    work_item_id = Column(String(36), ForeignKey("work_items.id"), nullable=False, index=True)
    item_version = Column(String(64), nullable=False)
    template = Column(String(64), nullable=False)
    active_key = Column(String(180), nullable=True)
    mode = Column(String(20), nullable=False)  # manual | auto
    status = Column(String(30), nullable=False, index=True)
    error_code = Column(String(80), nullable=True)
    error_detail = Column(String(400), nullable=True)
    runner = Column(String(20), nullable=False, default="governed", server_default="governed")
    model = Column(String(200), nullable=True)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    model_policy = Column(String(200), nullable=True)
    analysis_json = Column(JSON, nullable=True)
    tools_json = Column(JSON, nullable=True)
    cost_usd = Column(Numeric(12, 6), nullable=False, default=0)
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    board_message_id = Column(String(36), nullable=True)
    reporter_question = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    finished_at = Column(DateTime, nullable=True)


__all__ = ["WorkItemAnalysis"]
