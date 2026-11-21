"""Publish-time retrieval indexing for Engineering Knowledge Packs.

The per-record builders live in :mod:`.retrieval_index_records`; this module keeps the index
lifecycle (rebuild, deactivate) and decides which versions are active.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackVersion,
    EngineeringKnowledgeRetrievalIndex,
)
from ...time_utils import utc_now
from .retrieval_index_records import _fact_record, _item_record, _new_record, _pack_content, _source_record

ACTIVE_RETRIEVAL_VERSION_STATUS = "published"
ACTIVE_RETRIEVAL_QUALITY_STATUS = "passed"


async def rebuild_engineering_knowledge_retrieval_index(
    db: AsyncSession,
    *,
    pack_version_id: str,
) -> dict[str, Any]:
    version = await _load_version(db, pack_version_id=pack_version_id)
    if version is None:
        return {"status": "not_found", "indexed_record_count": 0, "active": False}

    await db.execute(
        delete(EngineeringKnowledgeRetrievalIndex).where(
            EngineeringKnowledgeRetrievalIndex.pack_version_id == pack_version_id
        )
    )
    is_active = _is_retrieval_active(version)
    if not is_active:
        await db.flush()
        return {"status": "inactive", "indexed_record_count": 0, "active": False}

    records = _build_index_records(version)
    for record in records:
        db.add(record)
    await db.flush()
    return {
        "status": "indexed",
        "indexed_record_count": len(records),
        "active": True,
        "record_kind_counts": _record_kind_counts(records),
    }


async def deactivate_engineering_knowledge_retrieval_index(
    db: AsyncSession,
    *,
    pack_version_id: str,
) -> dict[str, Any]:
    await db.execute(
        delete(EngineeringKnowledgeRetrievalIndex).where(
            EngineeringKnowledgeRetrievalIndex.pack_version_id == pack_version_id
        )
    )
    await db.flush()
    return {"status": "inactive", "indexed_record_count": 0, "active": False}


async def _load_version(
    db: AsyncSession,
    *,
    pack_version_id: str,
) -> EngineeringKnowledgePackVersion | None:
    return (
        await db.execute(
            select(EngineeringKnowledgePackVersion)
            .options(
                selectinload(EngineeringKnowledgePackVersion.pack),
                selectinload(EngineeringKnowledgePackVersion.sources),
                selectinload(EngineeringKnowledgePackVersion.items).selectinload(EngineeringKnowledgePackItem.source),
            )
            .where(EngineeringKnowledgePackVersion.id == pack_version_id)
        )
    ).scalar_one_or_none()


def _is_retrieval_active(version: EngineeringKnowledgePackVersion) -> bool:
    return (
        version.status == ACTIVE_RETRIEVAL_VERSION_STATUS
        and version.quality_status == ACTIVE_RETRIEVAL_QUALITY_STATUS
        and bool(version.pack and version.pack.is_active and version.pack.lifecycle_status == "active")
    )


def _build_index_records(version: EngineeringKnowledgePackVersion) -> list[EngineeringKnowledgeRetrievalIndex]:
    pack = version.pack
    if pack is None:
        return []
    now = utc_now()
    manifest = dict(version.manifest or {})
    evidence_ledger = list(manifest.get("evidence_ledger") or [])
    sources_by_key = {source.source_key: source for source in version.sources}
    records: list[EngineeringKnowledgeRetrievalIndex] = [
        _new_record(
            pack=pack,
            version=version,
            record_kind="pack",
            record_key=f"{pack.key}:v{version.version}",
            title=pack.name,
            summary=pack.description or "",
            content=_pack_content(version),
            indexed_at=now,
            metadata={
                "quality_report": dict(version.quality_report or {}),
                "compatibility_facts": dict(version.compatibility_facts or {}),
            },
        )
    ]
    records.extend(_source_record(pack, version, source, indexed_at=now) for source in version.sources)
    records.extend(_item_record(pack, version, item, indexed_at=now) for item in version.items)
    for fact in evidence_ledger:
        source = sources_by_key.get(str(fact.get("source_key") or ""))
        records.append(_fact_record(pack, version, fact, source=source, indexed_at=now))
    return records


def _record_kind_counts(records: list[EngineeringKnowledgeRetrievalIndex]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.record_kind] = counts.get(record.record_kind, 0) + 1
    return counts
