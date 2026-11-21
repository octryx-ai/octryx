"""Why a configured Workspace cannot be searched yet: a closed state, not ``needs_configuration``.

Searching a Workspace that was never ingested would otherwise answer
``503 needs_configuration`` ("Workspace knowledge storage is not configured."), which reads like a
broken instance. When the evidence runtime *is* configured but the Workspace's projection is missing
or not current, the reason is one of two states:

- ``no_sources``: the Workspace has no Knowledge source row at all; ingestion has never run. The
  answer is to add a source.
- ``projection_pending``: sources exist, but their projection (or its ACL marker) is not current
  yet. The answer is to wait for, or run, the projection.

``needs_configuration`` stays for real misconfiguration (no evidence runtime, no embedding space).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeEvidenceSource
from ..ledger.errors import EvidenceLedgerError, EvidenceNoSourcesError, EvidenceProjectionPendingError


async def unprojected_workspace_error(db: AsyncSession, project_id: str) -> EvidenceLedgerError:
    """The closed state of a Workspace whose projection is not current."""
    query = select(KnowledgeEvidenceSource.id).where(KnowledgeEvidenceSource.project_id == project_id).limit(1)
    has_source = (await db.execute(query)).first() is not None
    return EvidenceProjectionPendingError() if has_source else EvidenceNoSourcesError()


__all__ = ["unprojected_workspace_error"]
