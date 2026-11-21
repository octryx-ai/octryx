"""Pack CRUD and query helpers for Engineering Knowledge admin services."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackVersion,
)
from ._admin_engineering_knowledge_common import _pagination
from ._admin_engineering_knowledge_serialization import serialize_pack


def _pack_load_options() -> tuple[Any, ...]:
    return (
        selectinload(EngineeringKnowledgePack.versions).selectinload(EngineeringKnowledgePackVersion.sources),
        selectinload(EngineeringKnowledgePack.versions)
        .selectinload(EngineeringKnowledgePackVersion.items)
        .selectinload(EngineeringKnowledgePackItem.source),
        selectinload(EngineeringKnowledgePack.versions).selectinload(EngineeringKnowledgePackVersion.assignments),
    )


async def list_engineering_knowledge_packs(
    db: AsyncSession,
    *,
    stack_key: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    safe_limit, safe_offset = _pagination(limit, offset)
    stmt = select(EngineeringKnowledgePack)
    count_stmt = select(func.count()).select_from(EngineeringKnowledgePack)
    if stack_key:
        stmt = stmt.where(EngineeringKnowledgePack.stack_key == stack_key)
        count_stmt = count_stmt.where(EngineeringKnowledgePack.stack_key == stack_key)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    packs = (
        (
            await db.execute(
                stmt.options(*_pack_load_options())
                .order_by(EngineeringKnowledgePack.stack_key.asc(), EngineeringKnowledgePack.key.asc())
                .limit(safe_limit)
                .offset(safe_offset)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return {
        "packs": [serialize_pack(pack, include_details=False) for pack in packs],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "hasMore": safe_offset + len(packs) < total,
    }


async def get_engineering_knowledge_pack(db: AsyncSession, *, pack_id: str) -> dict[str, Any]:
    pack = (
        await db.execute(
            select(EngineeringKnowledgePack)
            .options(*_pack_load_options())
            .where(EngineeringKnowledgePack.id == pack_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if pack is None:
        pack = (
            await db.execute(
                select(EngineeringKnowledgePack)
                .options(*_pack_load_options())
                .where(EngineeringKnowledgePack.key == pack_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
    if pack is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge Pack not found")
    return serialize_pack(pack, include_details=True)


async def delete_engineering_knowledge_pack(db: AsyncSession, *, pack_id: str, admin_id: str) -> dict[str, Any]:
    pack = (
        await db.execute(
            select(EngineeringKnowledgePack).options(*_pack_load_options()).where(EngineeringKnowledgePack.id == pack_id)
        )
    ).scalar_one_or_none()
    if pack is None:
        pack = (
            await db.execute(
                select(EngineeringKnowledgePack)
                .options(*_pack_load_options())
                .where(EngineeringKnowledgePack.key == pack_id)
            )
        ).scalar_one_or_none()
    if pack is None:
        raise HTTPException(status_code=404, detail="Engineering Knowledge Pack not found")

    active_assignments = [
        assignment
        for version in pack.versions
        for assignment in (version.assignments or [])
        if assignment.assignment_status == "active"
    ]
    if active_assignments:
        raise HTTPException(
            status_code=400,
            detail="Engineering Knowledge Pack has active assignments and cannot be deleted",
        )

    deleted = {"id": pack.id, "key": pack.key, "deleted_by_user_id": admin_id}
    await db.delete(pack)
    await db.commit()
    return {**deleted, "deleted": True}
