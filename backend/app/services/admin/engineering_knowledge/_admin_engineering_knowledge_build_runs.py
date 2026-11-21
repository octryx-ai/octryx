"""Build-run helpers for Engineering Knowledge admin services."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import EngineeringKnowledgePackBuildRun
from ...engineering_knowledge import build_engineering_knowledge_pack_draft, pack_build_request_from_fields
from ._admin_engineering_knowledge_common import _pagination
from ._admin_engineering_knowledge_serialization import as_dict, serialize_build_run


async def list_engineering_knowledge_build_runs(
    db: AsyncSession,
    *,
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    safe_limit, safe_offset = _pagination(limit, offset)
    stmt = select(EngineeringKnowledgePackBuildRun)
    count_stmt = select(func.count()).select_from(EngineeringKnowledgePackBuildRun)
    if status:
        stmt = stmt.where(EngineeringKnowledgePackBuildRun.status == status)
        count_stmt = count_stmt.where(EngineeringKnowledgePackBuildRun.status == status)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    runs = (
        (
            await db.execute(
                stmt.options(
                    selectinload(EngineeringKnowledgePackBuildRun.pack),
                    selectinload(EngineeringKnowledgePackBuildRun.pack_version),
                )
                .order_by(EngineeringKnowledgePackBuildRun.started_at.desc())
                .limit(safe_limit)
                .offset(safe_offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "build_runs": [serialize_build_run(run) for run in runs],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "hasMore": safe_offset + len(runs) < total,
    }


async def create_engineering_knowledge_build_run(
    db: AsyncSession,
    *,
    admin_id: str,
    payload: dict[str, Any],
    archive_base_path: Path,
) -> dict[str, Any]:
    request = pack_build_request_from_fields(
        payload,
        source_policy=as_dict(payload.get("source_policy")),
        freshness_policy=as_dict(payload.get("freshness_policy")),
        publish_policy=as_dict(payload.get("publish_policy")),
    )
    if not request.is_pack_build_request:
        raise HTTPException(status_code=422, detail="target_versions are required")
    result = await build_engineering_knowledge_pack_draft(
        db,
        request=request,
        trigger="admin_api",
        archive_base_path=archive_base_path,
        source_overrides=as_dict(payload.get("source_overrides")),
        allowed_roots=[archive_base_path],
        allow_network=bool(payload.get("allow_network")),
        created_by_user_id=admin_id,
        max_download_bytes=int(payload.get("max_download_bytes") or 50 * 1024 * 1024),
    )
    await db.commit()
    return await get_engineering_knowledge_build_run(db, build_run_id=result.build_run.id)


async def get_engineering_knowledge_build_run(db: AsyncSession, *, build_run_id: str) -> dict[str, Any]:
    run = (
        await db.execute(
            select(EngineeringKnowledgePackBuildRun)
            .options(
                selectinload(EngineeringKnowledgePackBuildRun.pack),
                selectinload(EngineeringKnowledgePackBuildRun.pack_version),
            )
            .where(EngineeringKnowledgePackBuildRun.id == build_run_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge Pack build run not found")
    return serialize_build_run(run)
