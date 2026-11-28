"""Build a review-first Engineering Knowledge Pack draft from an explicit, structured request."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackBuildRun,
    EngineeringKnowledgePackVersion,
)
from ...time_utils import utc_now
from .manifest_export import export_engineering_knowledge_manifest
from .pack_build_request import EngineeringKnowledgePackBuildRequest
from .pack_builder_artifacts import _build_and_attach_evaluation_artifacts, _build_and_attach_evidence_artifacts
from .pack_builder_items import _create_items_from_archived_sources
from .pack_builder_quality import _build_compatibility_facts, _evaluate_manifest_quality
from .pack_builder_records import (
    _apply_source_overrides,
    _block_build_run,
    _create_pack_version,
    _get_or_create_pack,
    _new_build_run,
    _submit_for_review,
)
from .source_ingestion import DEFAULT_MAX_DOWNLOAD_BYTES, ingest_engineering_knowledge_source
from .source_ingestion_plan import generate_source_acquisition_plan

__all__ = [
    "EngineeringKnowledgePackBuildResult",
    "build_engineering_knowledge_pack_draft",
]


@dataclass(slots=True)
class EngineeringKnowledgePackBuildResult:
    request: EngineeringKnowledgePackBuildRequest
    build_run: EngineeringKnowledgePackBuildRun
    pack: EngineeringKnowledgePack | None
    pack_version: EngineeringKnowledgePackVersion | None
    manifest: dict[str, Any]
    quality_report: dict[str, Any]
    blockers: list[dict[str, str]]


async def build_engineering_knowledge_pack_draft(
    db: AsyncSession,
    *,
    request: EngineeringKnowledgePackBuildRequest,
    trigger: str,
    archive_base_path: Path,
    source_overrides: Mapping[str, str | Path] | None = None,
    allowed_roots: list[Path] | None = None,
    allow_network: bool = False,
    created_by_user_id: str | None = None,
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
) -> EngineeringKnowledgePackBuildResult:
    """Build a review-first draft for an explicit, structured ``request``."""
    if not request.is_pack_build_request:
        raise ValueError("build_engineering_knowledge_pack_draft requires an explicit pack build request")
    build_run = _new_build_run(
        request,
        trigger=trigger,
        source_overrides=source_overrides,
        allow_network=allow_network,
        created_by_user_id=created_by_user_id,
        max_download_bytes=max_download_bytes,
    )
    db.add(build_run)
    await db.flush()
    if request.blockers:
        return EngineeringKnowledgePackBuildResult(request, build_run, None, None, {}, {}, list(request.blockers))

    source_plan = generate_source_acquisition_plan(
        stack_key=request.stack_key,
        source_versions=request.source_versions,
        target_versions=request.target_versions,
        source_policy=request.source_policy,
    )
    build_run.source_plan = source_plan
    if not source_plan.get("sources"):
        return await _block_without_source_plan(db, request, build_run)

    pack, pack_version = await _create_pack_rows(db, request, build_run, created_by_user_id)
    await _ingest_planned_sources(
        db,
        request=request,
        pack=pack,
        pack_version=pack_version,
        source_specs=_apply_source_overrides(source_plan["sources"], source_overrides or {}),
        archive_base_path=archive_base_path,
        allowed_roots=allowed_roots,
        allow_network=allow_network,
        max_download_bytes=max_download_bytes,
    )
    await _attach_build_artifacts(db, request=request, pack_version=pack_version, archive_base_path=archive_base_path)
    return await _finish_build(db, request, build_run, pack, pack_version, source_plan)


async def _create_pack_rows(
    db: AsyncSession,
    request: EngineeringKnowledgePackBuildRequest,
    build_run: EngineeringKnowledgePackBuildRun,
    created_by_user_id: str | None,
) -> tuple[EngineeringKnowledgePack, EngineeringKnowledgePackVersion]:
    pack = await _get_or_create_pack(db, request=request, created_by_user_id=created_by_user_id)
    pack_version = await _create_pack_version(db, pack=pack, request=request, created_by_user_id=created_by_user_id)
    build_run.pack_id = pack.id
    build_run.pack_version_id = pack_version.id
    await db.flush()
    return pack, pack_version


async def _ingest_planned_sources(
    db: AsyncSession,
    *,
    request: EngineeringKnowledgePackBuildRequest,
    pack: EngineeringKnowledgePack,
    pack_version: EngineeringKnowledgePackVersion,
    source_specs: list[dict[str, Any]],
    archive_base_path: Path,
    allowed_roots: list[Path] | None,
    allow_network: bool,
    max_download_bytes: int,
) -> None:
    for source_spec in source_specs:
        await ingest_engineering_knowledge_source(
            db,
            pack_version=pack_version,
            pack_slug=pack.key,
            source_spec=source_spec,
            archive_base_path=archive_base_path,
            allowed_roots=allowed_roots,
            allow_network=allow_network,
            freshness_policy=request.freshness_policy,
            max_download_bytes=max_download_bytes,
        )
    await db.flush()


async def _block_without_source_plan(
    db: AsyncSession,
    request: EngineeringKnowledgePackBuildRequest,
    build_run: EngineeringKnowledgePackBuildRun,
) -> EngineeringKnowledgePackBuildResult:
    blockers = [
        {
            "code": "no_source_plan",
            "message": "No source acquisition plan could be generated for the requested stack and versions.",
        }
    ]
    _block_build_run(build_run, blockers)
    await db.flush()
    return EngineeringKnowledgePackBuildResult(request, build_run, None, None, {}, {}, blockers)


async def _attach_build_artifacts(
    db: AsyncSession,
    *,
    request: EngineeringKnowledgePackBuildRequest,
    pack_version: EngineeringKnowledgePackVersion,
    archive_base_path: Path,
) -> None:
    await _build_and_attach_evidence_artifacts(
        db,
        pack_version=pack_version,
        archive_base_path=archive_base_path,
        stack_key=request.stack_key,
        target_versions=request.target_versions,
    )
    await db.flush()

    await _create_items_from_archived_sources(
        db,
        pack_version=pack_version,
        archive_base_path=archive_base_path,
        stack_key=request.stack_key,
        target_versions=request.target_versions,
    )
    await _build_and_attach_evaluation_artifacts(db, pack_version=pack_version)


async def _finish_build(
    db: AsyncSession,
    request: EngineeringKnowledgePackBuildRequest,
    build_run: EngineeringKnowledgePackBuildRun,
    pack: EngineeringKnowledgePack,
    pack_version: EngineeringKnowledgePackVersion,
    source_plan: dict[str, Any],
) -> EngineeringKnowledgePackBuildResult:
    manifest = await export_engineering_knowledge_manifest(db, pack_version=pack_version)
    quality_report = _evaluate_manifest_quality(
        manifest,
        source_plan=source_plan,
        source_policy=request.source_policy,
    )
    pack_version.manifest = manifest
    pack_version.compatibility_facts = _build_compatibility_facts(
        manifest,
        stack_key=request.stack_key,
        source_versions=request.source_versions,
        target_versions=request.target_versions,
    )
    pack_version.quality_report = quality_report
    pack_version.quality_status = "passed" if quality_report["passed"] else "failed"
    blockers = list(quality_report.get("blockers") or [])
    if blockers:
        _block_build_run(build_run, blockers)
    else:
        _submit_for_review(build_run, pack_version)
    build_run.quality_report = quality_report
    build_run.completed_at = utc_now()
    await db.flush()
    return EngineeringKnowledgePackBuildResult(
        request,
        build_run,
        pack,
        pack_version,
        manifest,
        quality_report,
        blockers,
    )
