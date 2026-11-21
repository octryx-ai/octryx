"""Every indexed span carries its ACL marker: the convergence and the gate.

Retrieval admits a span only when its ``acl_keys`` intersect the caller's (``access/acl_keys.py``).
A restricted span is always written together with its marker in one upsert, so it is never
unmarked; a span without a marker is marked ``public`` by a bounded, idempotent statement that only
ever touches spans *without* a marker.

The convergence is recorded in PostgreSQL (``KnowledgeWorkspaceAclMarker``) before every projection
batch, and retrieval refuses a Workspace without that record (it has never been projected) with an
explicit state instead of an empty answer.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_source_acl import KnowledgeWorkspaceAclMarker
from ..access.acl_keys import PUBLIC_ACL_KEY
from ..evidence_index.base import EvidenceIndexClient
from ..evidence_index.errors import EvidenceIndexContractError
from ..evidence_index.operations import MARK_UNMARKED_EVIDENCE
from ..identity.workspace import WorkspaceId

logger = logging.getLogger(__name__)

ACL_MARKER_VERSION = 1
MARK_BATCH = 500
MAX_MARK_CALLS = 20


async def acl_marker_current(db: AsyncSession, project_id: str) -> bool:
    row = await db.get(KnowledgeWorkspaceAclMarker, project_id)
    return row is not None and int(row.marker_version) >= ACL_MARKER_VERSION


async def converge_acl_marker(db: AsyncSession, client: EvidenceIndexClient, workspace: WorkspaceId) -> bool:
    """Mark the Workspace's unmarked spans public, bounded. True once every span carries a marker."""
    if await acl_marker_current(db, workspace.canonical):
        return True
    for _ in range(MAX_MARK_CALLS):
        rows = await client.run(workspace, MARK_UNMARKED_EVIDENCE, {"acl_keys": [PUBLIC_ACL_KEY], "cap": MARK_BATCH})
        count = rows[0].get("count") if rows and isinstance(rows[0], dict) else None
        if type(count) is not int:
            raise EvidenceIndexContractError()
        if count < MARK_BATCH:
            break
    else:
        # More than the bound this run: the next run continues where this one stopped.
        return False
    db.add(KnowledgeWorkspaceAclMarker(project_id=workspace.canonical, marker_version=ACL_MARKER_VERSION))
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent convergence recorded it first; its record is equally valid.
        await db.rollback()
    logger.info("Knowledge ACL markers converged: workspace=%s", workspace.canonical)
    return True


__all__ = [
    "ACL_MARKER_VERSION",
    "acl_marker_current",
    "converge_acl_marker",
]
