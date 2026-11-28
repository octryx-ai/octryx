"""Where a parsed span sits in its document, and the parse the sandbox owes."""

from __future__ import annotations

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now

SPAN_KIND_TEXT = "text"
SPAN_KIND_HEADING = "heading"
SPAN_KIND_TABLE = "table"
SPAN_KIND_CODE = "code"
SPAN_KIND_LIST = "list"
ALL_SPAN_KINDS = frozenset({SPAN_KIND_TEXT, SPAN_KIND_HEADING, SPAN_KIND_TABLE, SPAN_KIND_CODE, SPAN_KIND_LIST})


class KnowledgeSpanLocator(WorkspaceBound, Base):
    """The structural locator of one parsed span."""

    __tablename__ = "knowledge_span_locators"
    __table_args__ = (
        Index("ix_knowledge_span_locators_workspace", "project_id"),
        CheckConstraint("page_start IS NULL OR page_start >= 1", name="ck_knowledge_span_locators_page_start"),
        CheckConstraint(
            "page_end IS NULL OR (page_start IS NOT NULL AND page_end >= page_start)",
            name="ck_knowledge_span_locators_page_range",
        ),
        CheckConstraint(
            "(line_start IS NULL AND line_end IS NULL) OR "
            "(line_start IS NOT NULL AND line_end IS NOT NULL AND line_start >= 1 AND line_end >= line_start)",
            name="ck_knowledge_span_locators_line_range",
        ),
    )

    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), primary_key=True)
    span_ordinal = Column(Integer, primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    # A code span's lines (``#L<start>-L<end>``); both null for every other span.
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    # Headings from the outermost to the nearest, each bounded (ingestion/docling_document.py).
    section_path = Column(JSON, nullable=False, default=list)


class KnowledgeParseTask(WorkspaceBound, Base):
    """The sandbox task one revision's ``parse_revision`` obligation is waiting for."""

    __tablename__ = "knowledge_parse_tasks"
    __table_args__ = (Index("ix_knowledge_parse_tasks_workspace", "project_id"),)

    revision_id = Column(String(36), ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    task_ref = Column(String(64), nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=utc_now)
