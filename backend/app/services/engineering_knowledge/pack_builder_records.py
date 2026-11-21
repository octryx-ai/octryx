"""Database rows a pack build creates or moves along: build run, pack and pack version."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackBuildRun,
    EngineeringKnowledgePackVersion,
)
from ...time_utils import utc_now
from .pack_build_request import EngineeringKnowledgePackBuildRequest


def _new_build_run(
    request: EngineeringKnowledgePackBuildRequest,
    *,
    trigger: str,
    source_overrides: Mapping[str, str | Path] | None,
    allow_network: bool,
    created_by_user_id: str | None,
    max_download_bytes: int,
) -> EngineeringKnowledgePackBuildRun:
    return EngineeringKnowledgePackBuildRun(
        id=str(uuid.uuid4()),
        trigger=trigger,
        prompt=request.prompt,
        stack_key=request.stack_key or None,
        source_versions=request.source_versions,
        target_versions=request.target_versions,
        status="blocked" if request.blockers else "running",
        acquisition_policy={
            "allow_network": allow_network,
            "source_overrides": sorted((source_overrides or {}).keys()),
            "max_download_bytes": max_download_bytes,
        },
        publish_decision="blocked" if request.blockers else "pending",
        approval_status="not_required",
        blocker_details=list(request.blockers),
        created_by_user_id=created_by_user_id,
    )


async def _get_or_create_pack(
    db: AsyncSession,
    *,
    request: EngineeringKnowledgePackBuildRequest,
    created_by_user_id: str | None,
) -> EngineeringKnowledgePack:
    existing = (
        await db.execute(select(EngineeringKnowledgePack).where(EngineeringKnowledgePack.key == request.pack_key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key=request.pack_key,
        name=request.pack_name,
        stack_key=request.stack_key,
        source_policy=request.source_policy,
        freshness_policy=request.freshness_policy,
        retrieval_policy={"default_context_budget_tokens": 12_000},
        resolution_policy={"ask_user_on_ambiguity": True},
        created_by_user_id=created_by_user_id,
    )
    db.add(pack)
    await db.flush()
    return pack


async def _create_pack_version(
    db: AsyncSession,
    *,
    pack: EngineeringKnowledgePack,
    request: EngineeringKnowledgePackBuildRequest,
    created_by_user_id: str | None,
) -> EngineeringKnowledgePackVersion:
    latest_version = (
        await db.execute(
            select(func.max(EngineeringKnowledgePackVersion.version)).where(
                EngineeringKnowledgePackVersion.pack_id == pack.id
            )
        )
    ).scalar_one()
    version_number = int(latest_version or 0) + 1
    pack_version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack_id=pack.id,
        version=version_number,
        status="draft",
        source_versions=request.source_versions,
        target_versions=request.target_versions,
        archive_root=f"engineering-knowledge/{pack.key}/v{version_number}",
        quality_status="pending",
        created_by_user_id=created_by_user_id,
    )
    db.add(pack_version)
    await db.flush()
    return pack_version


def _apply_source_overrides(
    sources: list[dict[str, Any]],
    source_overrides: Mapping[str, str | Path],
) -> list[dict[str, Any]]:
    updated_sources: list[dict[str, Any]] = []
    for source in sources:
        next_source = dict(source)
        source_key = str(next_source.get("source_key") or "").strip()
        if source_key in source_overrides:
            metadata = dict(next_source.get("metadata") or {})
            metadata["original_source_uri"] = next_source.get("source_uri")
            metadata["acquired_via"] = "source_override"
            next_source["metadata"] = metadata
            next_source["source_uri"] = str(source_overrides[source_key])
        updated_sources.append(next_source)
    return updated_sources


def _block_build_run(build_run: EngineeringKnowledgePackBuildRun, blockers: list[dict[str, str]]) -> None:
    build_run.status = "blocked"
    build_run.publish_decision = "blocked"
    build_run.approval_status = "not_required"
    build_run.blocker_details = blockers
    build_run.completed_at = utc_now()


def _submit_for_review(
    build_run: EngineeringKnowledgePackBuildRun,
    pack_version: EngineeringKnowledgePackVersion,
) -> None:
    pack_version.status = "pending_review"
    build_run.status = "pending_review"
    build_run.publish_decision = "requires_approval"
    build_run.approval_status = "pending"
