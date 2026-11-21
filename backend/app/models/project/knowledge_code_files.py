"""The code index of a ``git_repository`` Knowledge source: one row per tracked file (code module).

A repository source is one ``KnowledgeSourceConnector`` of kind ``git_repository``. Per-file sync
tracking (ledger source, content hash, version marker = git blob sha1) stays in
``KnowledgeSourceSyncItem``, like every connector. This table adds what the code module needs and
the sync item does not carry: the repository-relative **path**, the **language**, and the **code
elements** of the file at its blob (imports, annotations, configuration keys, dependencies, build
properties, each with its 1-based line). ``knowledge_code_impact`` joins change facts with these
elements without reading any object back.

Both fetch modes fill it through ``services/knowledge/code/repository_index.upsert_file``: the
launcher's ``local_snapshot`` upload and the ``remote_git`` fetch. The elements are derived from the
file text inside ``upsert_file``, so the two modes cannot disagree on them.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeCodeFile(Base):
    __tablename__ = "knowledge_code_files"
    __table_args__ = (
        UniqueConstraint("connector_id", "path_digest", name="uq_knowledge_code_files_path"),
        Index("ix_knowledge_code_files_workspace", "project_id"),
        Index("ix_knowledge_code_files_seen", "connector_id", "last_seen_commit"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    connector_id = Column(String(36), ForeignKey("knowledge_source_connectors.id", ondelete="CASCADE"), nullable=False)
    path = Column(String(1024), nullable=False)
    # sha256 of the path: the unique key (a 1024-character path is too long for an index).
    path_digest = Column(String(64), nullable=False)
    language = Column(String(40), nullable=True)
    # The git blob sha1 of the file's original bytes, and the commit it was indexed at.
    blob_sha = Column(String(40), nullable=False)
    commit_sha = Column(String(40), nullable=False)
    # The newest commit whose tree listed this path; a path not seen at the head commit is gone.
    last_seen_commit = Column(String(40), nullable=False)
    source_id = Column(String(36), nullable=True)
    revision_id = Column(String(36), nullable=True)
    # [[kind, value, line, detail], ...], bounded (``repository_index.MAX_ELEMENTS_PER_FILE``).
    elements = Column(JSON, nullable=False, default=list)
    element_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class KnowledgeCodeFileBlob(Base):
    """Every blob a path was indexed with: the platform viewer answers old links from it.

    One row per ``(connector, path, blob_sha)``, written when ``upsert_file`` records a new blob.
    A citation link carries the blob (``?blob=<sha>``), so a link to an older commit still opens
    exactly the content it cited, after the path moved on to a newer blob.
    """

    __tablename__ = "knowledge_code_file_blobs"
    __table_args__ = (
        UniqueConstraint("connector_id", "path_digest", "blob_sha", name="uq_knowledge_code_file_blobs_blob"),
        Index("ix_knowledge_code_file_blobs_workspace", "project_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    connector_id = Column(String(36), ForeignKey("knowledge_source_connectors.id", ondelete="CASCADE"), nullable=False)
    path_digest = Column(String(64), nullable=False)
    path = Column(String(1024), nullable=False)
    blob_sha = Column(String(40), nullable=False)
    # The commit the blob was first indexed at, and the ledger revision that holds its text.
    first_commit = Column(String(40), nullable=False)
    source_id = Column(String(36), nullable=True)
    revision_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["KnowledgeCodeFile", "KnowledgeCodeFileBlob"]
