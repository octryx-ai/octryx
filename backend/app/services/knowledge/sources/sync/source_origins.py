"""Where each Knowledge source comes from, for Knowledge → Documents.

Read from stored lineage only, never from the shape of a source key:

- a source is ``connector`` when a Source Sync item of the Workspace records its key (the item's
  stored ``source_key``, which survives retirement while ``source_id`` is cleared). The connector's
  kind and key come from the item's connector, ``url`` from the newest revision's stored origin
  (``KnowledgeSourceRevisionOrigin``), and ``removed_at_source`` from the item's ``retired`` state;
- every other source is ``upload``, meaning no Source Sync lineage is recorded. This includes a
  source kept after its connector was deleted, because the connector's items are deleted with it.

``withheld`` (restricted at the source) is not ``removed_at_source``.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_evidence import KnowledgeSourceRevision
from .....models.project.knowledge_evidence import KnowledgeSourceRevisionOrigin as Origin
from .....models.project.knowledge_source_sync import (
    ITEM_STATE_RETIRED,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncItem,
)

ORIGIN_UPLOAD = "upload"
ORIGIN_CONNECTOR = "connector"


async def source_origins(
    db: AsyncSession, project_id: str, sources: Iterable[tuple[str, str]]
) -> dict[str, dict[str, object]]:
    """``{source_id: origin}`` for ``(source_id, source_key)`` pairs of one Workspace (a bounded page)."""
    pairs = list(sources)
    if not pairs:
        return {}
    keys = {key for _, key in pairs}
    items = (
        await db.execute(
            select(
                KnowledgeSourceSyncItem.source_key,
                KnowledgeSourceSyncItem.state,
                KnowledgeSourceConnector.kind,
                KnowledgeSourceConnector.connector_key,
            )
            .join(KnowledgeSourceConnector, KnowledgeSourceConnector.id == KnowledgeSourceSyncItem.connector_id)
            .where(
                KnowledgeSourceSyncItem.project_id == project_id,
                KnowledgeSourceConnector.project_id == project_id,
                KnowledgeSourceSyncItem.source_key.in_(keys),
            )
        )
    ).all()
    synced = {row.source_key: row for row in items}
    links = await _newest_origin_urls(db, project_id, [sid for sid, key in pairs if key in synced])
    origins: dict[str, dict[str, object]] = {}
    for source_id, key in pairs:
        item = synced.get(key)
        if item is None:
            origins[source_id] = {"type": ORIGIN_UPLOAD}
            continue
        origins[source_id] = {
            "type": ORIGIN_CONNECTOR,
            "connector_kind": item.kind,
            "connector_key": item.connector_key,
            "url": links.get(source_id),
            "removed_at_source": item.state == ITEM_STATE_RETIRED,
        }
    return origins


async def _newest_origin_urls(db: AsyncSession, project_id: str, source_ids: list[str]) -> dict[str, str]:
    """The stored origin link of each source's newest revision that has one."""
    if not source_ids:
        return {}
    rows = (
        await db.execute(
            select(KnowledgeSourceRevision.source_id, Origin.source_url)
            .join(Origin, Origin.revision_id == KnowledgeSourceRevision.id)
            .where(
                KnowledgeSourceRevision.project_id == project_id,
                Origin.project_id == project_id,
                KnowledgeSourceRevision.source_id.in_(source_ids),
            )
            .order_by(KnowledgeSourceRevision.source_id, KnowledgeSourceRevision.revision_ordinal.desc())
        )
    ).all()
    newest: dict[str, str] = {}
    for source_id, url in rows:
        newest.setdefault(source_id, url)
    return newest


__all__ = ["ORIGIN_CONNECTOR", "ORIGIN_UPLOAD", "source_origins"]
