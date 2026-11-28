"""Why a configured Workspace cannot be searched yet: a closed state, not ``needs_configuration``."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeEvidenceSource
from ..ledger.errors import EvidenceLedgerError, EvidenceNoSourcesError, EvidenceProjectionPendingError


async def unprojected_workspace_error(db: AsyncSession, project_id: str) -> EvidenceLedgerError:
    query = select(KnowledgeEvidenceSource.id).where(KnowledgeEvidenceSource.project_id == project_id).limit(1)
    has_source = (await db.execute(query)).first() is not None
    return EvidenceProjectionPendingError() if has_source else EvidenceNoSourcesError()


__all__ = ["unprojected_workspace_error"]
