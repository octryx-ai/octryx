"""Which coding pipeline configs a work item may use."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkCodingPipelineConfig, WorkItem
from ..coding_serializers import serialize_coding_pipeline_config
from ..related_rows import PIPELINE_CONFIG, load_related


def _for_item(item: WorkItem):
    return (WorkCodingPipelineConfig.project_id == item.project_id) | WorkCodingPipelineConfig.project_id.is_(None)


async def item_pipeline_configs(db: AsyncSession, item: WorkItem) -> list[dict[str, Any]]:
    stmt = select(WorkCodingPipelineConfig).where(_for_item(item), WorkCodingPipelineConfig.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(WorkCodingPipelineConfig.name.asc()))).scalars().all()
    return [serialize_coding_pipeline_config(row) for row in rows]


async def resolve_item_pipeline_config(
    db: AsyncSession, viewer: User, config_id: str | None, item: WorkItem
) -> WorkCodingPipelineConfig | None:
    # Only a config ``viewer`` may use, of the item's Workspace or a global one; by default the item's own before a
    # global one.
    if config_id:
        return await load_related(db, viewer, PIPELINE_CONFIG, config_id, for_workspace=item.project_id)
    stmt = (
        select(WorkCodingPipelineConfig)
        .where(WorkCodingPipelineConfig.is_active.is_(True), _for_item(item))
        .order_by(WorkCodingPipelineConfig.project_id.is_(None).asc(), WorkCodingPipelineConfig.updated_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


__all__ = ["item_pipeline_configs", "resolve_item_pipeline_config"]
