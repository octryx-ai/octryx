"""Research-built knowledge packages of a Workspace (Knowledge, research packages).

A package is general knowledge about a product and its versions (for example the Spring Boot 3.5
to 4.0 upgrade) that a governed research run assembled from the web: which sources are
authoritative, which version each covers, and why. It is a proposal until an author approves it;
only approved documents are fetched and ingested, as ordinary sources with the product, version
and origin link the research gave them.

``KnowledgePackage.research`` keeps the provenance of the run: the search queries, the search
provider that answered, and the model usage. No page content is stored here; fetched documents live
in the evidence ledger like any upload.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text

from ...db import Base
from ...time_utils import utc_now

PACKAGE_STATE_DRAFT = "draft"
PACKAGE_STATE_SYNCING = "syncing"
PACKAGE_STATE_READY = "ready"
PACKAGE_STATE_FAILED = "failed"

DOCUMENT_STATE_PROPOSED = "proposed"
DOCUMENT_STATE_ACCEPTED = "accepted"
DOCUMENT_STATE_REJECTED = "rejected"
DOCUMENT_STATE_INGESTED = "ingested"
DOCUMENT_STATE_FAILED = "failed"


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgePackage(Base):
    __tablename__ = "knowledge_packages"
    __table_args__ = (Index("ix_knowledge_packages_workspace", "project_id"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    topic = Column(String(500), nullable=False)
    title = Column(String(300), nullable=False)
    product = Column(String(60), nullable=False)
    versions = Column(JSON, nullable=False, default=list)
    state = Column(String(20), nullable=False, default=PACKAGE_STATE_DRAFT)
    research = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgePackageDocument(Base):
    __tablename__ = "knowledge_package_documents"
    __table_args__ = (Index("ix_knowledge_package_documents_package", "package_id"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    package_id = Column(String(36), ForeignKey("knowledge_packages.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    url = Column(String(2048), nullable=False)
    title = Column(String(300), nullable=False)
    version = Column(String(40), nullable=True)
    role = Column(String(40), nullable=False)
    rationale = Column(Text, nullable=False, default="")
    state = Column(String(20), nullable=False, default=DOCUMENT_STATE_PROPOSED)
    outcome = Column(String(40), nullable=True)
    source_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
