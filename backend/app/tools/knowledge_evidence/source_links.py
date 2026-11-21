"""Openable citations for the Knowledge evidence the model sees.

A passage keeps its source's own link (the ledger's ``source_url``, e.g. a public web page). A passage of
an uploaded source has no such link; when it comes from the reading Workspace itself, it cites the exact
revision through the existing authenticated original route
(``services/answer_evidence/knowledge_original_links``). Opening that link authorizes the Workspace, the
source's visibility and its tombstone state again, so the link grants nothing by itself.

A passage from a bound Workspace gets no manufactured link: the reader reads it on that Workspace's behalf
and has no direct original access there. Nothing is derived from a Workspace's display name. No object
key, presigned URL, token or local path is ever exposed.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.project.knowledge_evidence import REVISION_STATE_TOMBSTONED, KnowledgeSourceRevision
from ...services.answer_evidence.knowledge_original_links import knowledge_original_path
from ...services.knowledge.retrieval.locator import line_range, markdown_citation


def openable_source_url(
    *, source_url: str | None, workspace_id: str, primary_workspace_id: str, source_id: str, revision_id: str
) -> str | None:
    """The source's own link, else the reading Workspace's original of this exact revision, else ``None``."""
    if source_url:
        return source_url
    if not workspace_id or workspace_id != primary_workspace_id:
        return None
    return knowledge_original_path(primary_workspace_id, source_id, revision_id)


def presented_citation(
    citation: Any, *, workspace_id: str, primary_workspace_id: str
) -> dict[str, str | None]:
    """``source_url`` and the matching ``cite_as`` of a cited span or fact citation."""
    url = openable_source_url(
        source_url=getattr(citation, "source_url", None),
        workspace_id=workspace_id,
        primary_workspace_id=primary_workspace_id,
        source_id=str(getattr(citation, "source_id", "") or ""),
        revision_id=str(getattr(citation, "revision_id", "") or ""),
    )
    title = str(getattr(citation, "source_title", "") or "")
    section_path = tuple(getattr(citation, "section_path", ()) or ())
    return {"source_url": url, "cite_as": markdown_citation(title, url, section_path, line_range(citation))}


def _revision_of(evidence_key: object) -> str | None:
    """The revision id an evidence key names (``<revision_hex>:<ordinal>``), in the ledger's form."""
    if not isinstance(evidence_key, str) or ":" not in evidence_key:
        return None
    try:
        return str(uuid.UUID(hex=evidence_key.split(":", 1)[0]))
    except ValueError:
        return None


async def read_source_url(
    db: AsyncSession, *, source_url: str | None, workspace_id: str, primary_workspace_id: str, evidence_key: object
) -> str | None:
    """``openable_source_url`` for a ``knowledge_read`` window, whose read names only the evidence key."""
    if source_url or not workspace_id or workspace_id != primary_workspace_id:
        return source_url or None
    revision_id = _revision_of(evidence_key)
    if revision_id is None:
        return None
    source_id = (
        await db.execute(
            select(KnowledgeSourceRevision.source_id).where(
                KnowledgeSourceRevision.id == revision_id,
                KnowledgeSourceRevision.project_id == primary_workspace_id,
                KnowledgeSourceRevision.state != REVISION_STATE_TOMBSTONED,
            )
        )
    ).scalar_one_or_none()
    if source_id is None:
        return None
    return knowledge_original_path(primary_workspace_id, source_id, revision_id)


__all__ = ["openable_source_url", "presented_citation", "read_source_url"]
