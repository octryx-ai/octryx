"""Default Python Engineering Knowledge Pack seeding."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackAssignment,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)
from ...time_utils import utc_now
from ._python_default_pack_documents import (
    _ACQUISITION_MODE,
    _STACK_KEY,
    _build_compatibility_facts,
    _build_quality_report,
    _evidence_payload,
    _seed_document,
)
from ._python_default_pack_seed_data import (
    PYTHON312_ENGINEERING_PACK_KEY,
    PYTHON312_FRESHNESS_POLICY,
    PYTHON312_RESOLUTION_POLICY,
    PYTHON312_RETRIEVAL_POLICY,
    PYTHON312_SOURCE_POLICY,
    PYTHON312_SOURCE_SPECS,
    PYTHON312_SOURCE_VERSIONS,
    PYTHON312_TARGETS,
    PYTHON312_TOOLCHAIN_POLICY,
)
from .archive_paths import build_source_archive_paths
from .archive_store import write_engineering_archive_text
from .manifest_export import export_engineering_knowledge_manifest

_VERSION_NUMBER = 1


async def ensure_default_python_engineering_knowledge_pack(
    db: AsyncSession,
    *,
    archive_base_path: Path,
) -> EngineeringKnowledgePackVersion:
    """Ensure the built-in Python Engineering Knowledge Pack exists."""

    pack = await _get_or_create_pack(db)
    version = await _get_or_create_version(db, pack=pack)
    await _upsert_sources_and_items(db, pack=pack, version=version, archive_base_path=archive_base_path)
    manifest = await export_engineering_knowledge_manifest(db, pack_version=version)
    version.manifest = manifest
    version.compatibility_facts = _build_compatibility_facts(manifest)
    version.quality_report = _build_quality_report(manifest)
    version.quality_status = "passed"
    version.status = "published"
    version.published_at = version.published_at or utc_now()
    await _ensure_global_assignment(db, version=version)
    await db.flush()
    return version


async def _get_or_create_pack(db: AsyncSession) -> EngineeringKnowledgePack:
    pack = (
        await db.execute(
            select(EngineeringKnowledgePack).where(EngineeringKnowledgePack.key == PYTHON312_ENGINEERING_PACK_KEY)
        )
    ).scalar_one_or_none()
    if pack is None:
        pack = EngineeringKnowledgePack(id=str(uuid.uuid4()), key=PYTHON312_ENGINEERING_PACK_KEY)
        db.add(pack)
    pack.name = "Python 3.12 Engineering Knowledge Pack"
    pack.description = (
        "Default Python pack skeleton for runtime migration and code-quality tasks. "
        "It proves Engineering Knowledge Packs are stack-generic and can be refreshed by the pack builder."
    )
    pack.stack_key = _STACK_KEY
    pack.lifecycle_status = "active"
    pack.source_policy = PYTHON312_SOURCE_POLICY
    pack.freshness_policy = PYTHON312_FRESHNESS_POLICY
    pack.retrieval_policy = PYTHON312_RETRIEVAL_POLICY
    pack.toolchain_policy = PYTHON312_TOOLCHAIN_POLICY
    pack.resolution_policy = PYTHON312_RESOLUTION_POLICY
    pack.is_active = True
    await db.flush()
    return pack


async def _get_or_create_version(
    db: AsyncSession,
    *,
    pack: EngineeringKnowledgePack,
) -> EngineeringKnowledgePackVersion:
    version = (
        await db.execute(
            select(EngineeringKnowledgePackVersion).where(
                EngineeringKnowledgePackVersion.pack_id == pack.id,
                EngineeringKnowledgePackVersion.version == _VERSION_NUMBER,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        version = EngineeringKnowledgePackVersion(id=str(uuid.uuid4()), pack_id=pack.id, version=_VERSION_NUMBER)
        db.add(version)
    version.source_versions = PYTHON312_SOURCE_VERSIONS
    version.target_versions = PYTHON312_TARGETS
    version.archive_root = f"engineering-knowledge/{pack.key}/v{_VERSION_NUMBER}"
    version.notes = (
        "Built-in stack-generic seed. Source rows use official or vendor URIs and archived curated seed snapshots; "
        "refresh jobs may replace them with live fetched evidence."
    )
    await db.flush()
    return version


async def _upsert_sources_and_items(
    db: AsyncSession,
    *,
    pack: EngineeringKnowledgePack,
    version: EngineeringKnowledgePackVersion,
    archive_base_path: Path,
) -> None:
    for index, spec in enumerate(PYTHON312_SOURCE_SPECS, start=1):
        archive = _write_seed_archive(
            spec,
            pack_key=pack.key,
            version_number=version.version,
            archive_base_path=archive_base_path,
        )
        source = await _upsert_source(db, version=version, spec=spec, archive=archive)
        await _upsert_item(db, version=version, source=source, spec=spec, rank=index * 10)
    await db.flush()


async def _upsert_source(
    db: AsyncSession,
    *,
    version: EngineeringKnowledgePackVersion,
    spec: dict[str, Any],
    archive: dict[str, str],
) -> EngineeringKnowledgePackSource:
    source = (
        await db.execute(
            select(EngineeringKnowledgePackSource).where(
                EngineeringKnowledgePackSource.pack_version_id == version.id,
                EngineeringKnowledgePackSource.source_key == spec["source_key"],
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = EngineeringKnowledgePackSource(id=str(uuid.uuid4()), pack_version_id=version.id)
        db.add(source)
    source.source_key = spec["source_key"]
    source.title = spec["title"]
    source.source_uri = spec["source_uri"]
    source.source_type = spec["source_type"]
    source.trust_tier = spec["trust_tier"]
    source.version_label = spec["version_label"]
    source.checksum = archive["checksum"]
    source.fetch_status = "fetched"
    source.freshness_status = "fresh"
    source.raw_archive_path = archive["raw_archive_path"]
    source.parsed_archive_path = archive["parsed_archive_path"]
    source.evidence_archive_path = archive["evidence_archive_path"]
    source.source_metadata = {
        **dict(spec.get("metadata") or {}),
        "official_source_uri": spec["source_uri"],
        "final_uri": spec["source_uri"],
        "acquisition_mode": _ACQUISITION_MODE,
        "seed_snapshot": True,
    }
    await db.flush()
    return source


async def _upsert_item(
    db: AsyncSession,
    *,
    version: EngineeringKnowledgePackVersion,
    source: EngineeringKnowledgePackSource,
    spec: dict[str, Any],
    rank: int,
) -> None:
    item_key = f"{spec['source_key']}-seed-baseline"
    item = (
        await db.execute(
            select(EngineeringKnowledgePackItem).where(
                EngineeringKnowledgePackItem.pack_version_id == version.id,
                EngineeringKnowledgePackItem.item_key == item_key,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        item = EngineeringKnowledgePackItem(id=str(uuid.uuid4()), pack_version_id=version.id, item_key=item_key)
        db.add(item)
    item.source_id = source.id
    item.title = spec["title"]
    item.summary = spec["summary"]
    item.content = _seed_document(spec)
    item.tags = [_STACK_KEY, *list(spec.get("tags") or [])]
    item.triggers = ["python-3.12", "migration", "code-quality"]
    item.version_scope = {
        "target_versions": PYTHON312_TARGETS,
        "target_exactness": {"python": "exact_minor"},
    }
    item.retrieval_priority = "high" if spec["trust_tier"] == "official" else "normal"
    item.retrieval_rank = rank
    item.item_metadata = {
        "acquisition_mode": _ACQUISITION_MODE,
        "official_source_uri": spec["source_uri"],
    }


def _write_seed_archive(
    spec: dict[str, Any],
    *,
    pack_key: str,
    version_number: int,
    archive_base_path: Path,
) -> dict[str, str]:
    paths = build_source_archive_paths(pack_slug=pack_key, pack_version=version_number, source_key=spec["source_key"])
    payload = _seed_document(spec)
    encoded = payload.encode("utf-8")
    checksum = hashlib.sha256(encoded).hexdigest()
    raw_path = str(Path(paths.raw) / f"{spec['source_key']}.md")
    parsed_path = str(Path(paths.parsed) / f"{spec['source_key']}.md")
    evidence_path = str(Path(paths.evidence) / "evidence.json")
    write_engineering_archive_text(raw_path, payload, content_type="text/markdown")
    write_engineering_archive_text(parsed_path, payload, content_type="text/markdown")
    evidence_payload = json.dumps(_evidence_payload(spec, checksum), indent=2, ensure_ascii=False)
    write_engineering_archive_text(evidence_path, evidence_payload, content_type="application/json")
    return {
        "checksum": checksum,
        "raw_archive_path": raw_path,
        "parsed_archive_path": parsed_path,
        "evidence_archive_path": evidence_path,
    }


async def _ensure_global_assignment(db: AsyncSession, *, version: EngineeringKnowledgePackVersion) -> None:
    assignment = (
        await db.execute(
            select(EngineeringKnowledgePackAssignment).where(
                EngineeringKnowledgePackAssignment.pack_version_id == version.id,
                EngineeringKnowledgePackAssignment.scope_type == "global",
                EngineeringKnowledgePackAssignment.scope_id.is_(None),
                EngineeringKnowledgePackAssignment.workspace_id.is_(None),
                EngineeringKnowledgePackAssignment.repository_id.is_(None),
                EngineeringKnowledgePackAssignment.stack_key == _STACK_KEY,
            )
        )
    ).scalar_one_or_none()
    active_other = (
        await db.execute(
            select(EngineeringKnowledgePackAssignment).where(
                EngineeringKnowledgePackAssignment.pack_version_id != version.id,
                EngineeringKnowledgePackAssignment.scope_type == "global",
                EngineeringKnowledgePackAssignment.scope_id.is_(None),
                EngineeringKnowledgePackAssignment.workspace_id.is_(None),
                EngineeringKnowledgePackAssignment.repository_id.is_(None),
                EngineeringKnowledgePackAssignment.stack_key == _STACK_KEY,
                EngineeringKnowledgePackAssignment.assignment_status == "active",
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        assignment = EngineeringKnowledgePackAssignment(id=str(uuid.uuid4()), pack_version_id=version.id)
        db.add(assignment)
    assignment.scope_type = "global"
    assignment.stack_key = _STACK_KEY
    assignment.assignment_status = "inactive" if active_other is not None else "active"
    assignment.priority = 100
    assignment.assignment_policy = {"resolution": "automatic", "manual_user_selection": False, "seed_default": True}
    assignment.assigned_at = assignment.assigned_at or utc_now()
    await db.flush()
