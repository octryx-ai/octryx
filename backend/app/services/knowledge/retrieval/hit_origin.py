"""Where a search hit comes from, in the reader's words.

A hit names its source document; the Search page also needs the system it was synced from (Confluence, Jira,
ServiceNow, a Git repository, or an upload), the space or project it belongs to, and when Octryx AI received
this version. All of it is read from stored lineage, never guessed from a title:

- ``origin``: ``source_origins()`` (``sources/sync/source_origins.py``), the same lineage Knowledge → Documents uses.
  ``kind`` is the connector's kind, or ``upload`` when no Source Sync item records the source.
- ``container``: a Jira issue's project from its issue key (the item's ``external_id``); a Confluence page's space
  only when its connector reads exactly one space (the page's own space is not stored per item); otherwise none.
- ``changed_at``: when the hit's revision was registered: the date Octryx AI received the version.
- ``origin.source_changed_at``: when the content changed at its source (Confluence ``version.when``, Jira
  ``fields.updated``, ServiceNow ``sys_updated_on``), stored with the revision's origin; ``None`` for uploads and
  when the source reported no date (the UI then shows ``changed_at``).

Bounded: a few queries per Workspace of one result page, whatever the number of hits.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
    KnowledgeSourceRevisionOrigin,
)
from ....models.project.knowledge_source_sync import KnowledgeSourceConnector, KnowledgeSourceSyncItem
from ....time_utils import ensure_utc
from ..sources.sync.confluence_scope import scope_space_keys
from ..sources.sync.source_origins import ORIGIN_UPLOAD, source_origins

KIND_JIRA = "jira"
KIND_CONFLUENCE = "confluence"
_JIRA_KEY = re.compile(r"^([A-Z][A-Z0-9_]*)-\d+$")

HitRef = tuple[str, str, str]  # (workspace_id, source_id, revision_id)


def _container(kind: str | None, external_id: str | None, scope: object) -> str | None:
    if kind == KIND_JIRA and external_id:
        match = _JIRA_KEY.match(external_id.strip())
        return match.group(1) if match else None
    if kind == KIND_CONFLUENCE and isinstance(scope, dict):
        spaces = {space for space in scope_space_keys(scope) if space}
        return next(iter(spaces)) if len(spaces) == 1 else None
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


async def _sync_items(db: AsyncSession, workspace_id: str, source_keys: set[str]) -> dict[str, object]:
    """The Source Sync item and its connector's scope, by source key."""
    items = (
        await db.execute(
            select(
                KnowledgeSourceSyncItem.source_key, KnowledgeSourceSyncItem.external_id, KnowledgeSourceConnector.scope
            )
            .join(KnowledgeSourceConnector, KnowledgeSourceConnector.id == KnowledgeSourceSyncItem.connector_id)
            .where(
                KnowledgeSourceSyncItem.project_id == workspace_id,
                KnowledgeSourceConnector.project_id == workspace_id,
                KnowledgeSourceSyncItem.source_key.in_(source_keys),
            )
        )
    ).all()
    return {row.source_key: row for row in items}


def _origin_entry(found: dict[str, object], item: object) -> dict[str, object]:
    if found.get("type") == ORIGIN_UPLOAD:
        return {"origin": {"kind": ORIGIN_UPLOAD, "connector_key": None, "url": None}, "container": None}
    kind = str(found.get("connector_kind") or "") or None
    return {
        "origin": {"kind": kind, "connector_key": found.get("connector_key"), "url": found.get("url")},
        "container": _container(kind, item.external_id if item else None, item.scope if item else None),
    }


async def _revision_dates(
    db: AsyncSession, workspace_id: str, revision_ids: set[str]
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """When each revision was registered, and when its content changed at the source (when recorded)."""
    if not revision_ids:
        return {}, {}
    changed = dict(
        (
            await db.execute(
                select(KnowledgeSourceRevision.id, KnowledgeSourceRevision.created_at).where(
                    KnowledgeSourceRevision.project_id == workspace_id, KnowledgeSourceRevision.id.in_(revision_ids)
                )
            )
        ).all()
    )
    source_dates = dict(
        (
            await db.execute(
                select(KnowledgeSourceRevisionOrigin.revision_id, KnowledgeSourceRevisionOrigin.source_changed_at)
                .where(KnowledgeSourceRevisionOrigin.project_id == workspace_id,
                       KnowledgeSourceRevisionOrigin.revision_id.in_(revision_ids))
            )
        ).all()
    )
    return {revision_id: _iso(created) for revision_id, created in changed.items()}, {
        revision_id: _iso(ensure_utc(value)) for revision_id, value in source_dates.items() if value is not None}


async def _workspace_origins(
    db: AsyncSession, workspace_id: str, source_ids: set[str], revision_ids: set[str]
) -> tuple[dict[str, dict[str, object]], dict[str, str | None], dict[str, str | None]]:
    keys = dict(
        (
            await db.execute(
                select(KnowledgeEvidenceSource.id, KnowledgeEvidenceSource.source_key).where(
                    KnowledgeEvidenceSource.project_id == workspace_id, KnowledgeEvidenceSource.id.in_(source_ids)
                )
            )
        ).all()
    )
    lineage = await source_origins(db, workspace_id, keys.items())
    by_key = await _sync_items(db, workspace_id, set(keys.values())) if keys else {}
    origins: dict[str, dict[str, object]] = {}
    for source_id, source_key in keys.items():
        found = lineage.get(source_id) or {"type": ORIGIN_UPLOAD}
        origins[source_id] = _origin_entry(found, by_key.get(source_key))
    changed, source_changed = await _revision_dates(db, workspace_id, revision_ids)
    return origins, changed, source_changed


async def hit_origins(db: AsyncSession, hits: Iterable[HitRef]) -> dict[HitRef, dict[str, object]]:
    """``{(workspace_id, source_id, revision_id): {"origin", "container", "changed_at"}}`` for one result page."""
    refs = list(dict.fromkeys(hits))
    per_workspace: dict[str, tuple[set[str], set[str]]] = defaultdict(lambda: (set(), set()))
    for workspace_id, source_id, revision_id in refs:
        sources, revisions = per_workspace[workspace_id]
        if source_id:
            sources.add(source_id)
        if revision_id:
            revisions.add(revision_id)
    answer: dict[HitRef, dict[str, object]] = {}
    for workspace_id, (sources, revisions) in per_workspace.items():
        origins, changed, source_changed = await _workspace_origins(db, workspace_id, sources, revisions)
        for ref in refs:
            if ref[0] != workspace_id:
                continue
            found = origins.get(ref[1]) or {"origin": None, "container": None}
            origin = found.get("origin")
            if isinstance(origin, dict):
                origin = {**origin, "source_changed_at": source_changed.get(ref[2])}
            answer[ref] = {**found, "origin": origin, "changed_at": changed.get(ref[2])}
    return answer


__all__ = ["HitRef", "hit_origins"]
