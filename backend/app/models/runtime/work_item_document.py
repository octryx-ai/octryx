"""A documentation page a workflow run published for a Work item (Workflow B's documentation phase).

One row per Work item and page: created on the first publish, updated (version, title, URL, run) on every later
one, so the Work item always links its current page and a later run updates that page instead of creating another.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


class WorkItemDocument(Base):
    __tablename__ = "work_item_documents"
    # The same page id on another connection or Confluence instance is another page.
    __table_args__ = (UniqueConstraint("work_item_id", "provider", "connection_id", "instance_url", "page_id",
                                       name="uq_work_item_documents_page_ref"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_item_id = Column(String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    provider = Column(String(40), nullable=False, default="confluence")
    # The connection that served the page: the same space and id on another Confluence is another page.
    connection_id = Column(String(64), nullable=True)
    # The normalized, non-secret base URL of the Confluence the page lives on (tools/_confluence_instance).
    instance_url = Column(String(500), nullable=True)
    space_key = Column(String(120), nullable=False)
    page_id = Column(String(64), nullable=False)
    title = Column(String(500), nullable=False)
    url = Column(Text, nullable=True)
    version = Column(Integer, nullable=True)
    run_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
