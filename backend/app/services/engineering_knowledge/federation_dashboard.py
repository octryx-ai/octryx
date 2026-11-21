"""Engineering Knowledge federation dashboard queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    EngineeringKnowledgeFederationFeed,
    EngineeringKnowledgeFederationPackage,
    EngineeringKnowledgeFederationSyncRun,
)
from .federation_operations import federation_operational_summary
from .federation_serializers import (
    serialize_federation_feed,
    serialize_federation_package,
    serialize_federation_sync_run,
)


async def get_engineering_knowledge_federation_dashboard(db: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 50), 200))
    feeds = (
        (
            await db.execute(
                select(EngineeringKnowledgeFederationFeed)
                .order_by(EngineeringKnowledgeFederationFeed.updated_at.desc())
                .limit(safe_limit)
            )
        )
        .scalars()
        .all()
    )
    packages = (
        (
            await db.execute(
                select(EngineeringKnowledgeFederationPackage)
                .options(selectinload(EngineeringKnowledgeFederationPackage.feed))
                .order_by(EngineeringKnowledgeFederationPackage.created_at.desc())
                .limit(safe_limit)
            )
        )
        .scalars()
        .all()
    )
    sync_runs = (
        (
            await db.execute(
                select(EngineeringKnowledgeFederationSyncRun)
                .options(selectinload(EngineeringKnowledgeFederationSyncRun.feed))
                .order_by(EngineeringKnowledgeFederationSyncRun.started_at.desc())
                .limit(safe_limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "feeds": [serialize_federation_feed(feed) for feed in feeds],
        "packages": [serialize_federation_package(package) for package in packages],
        "sync_runs": [serialize_federation_sync_run(run) for run in sync_runs],
        "summary": {
            "feed_count": await _count(db, EngineeringKnowledgeFederationFeed.id),
            "package_count": await _count(db, EngineeringKnowledgeFederationPackage.id),
            "pending_review_count": await _count_where(
                db,
                EngineeringKnowledgeFederationPackage.review_status == "pending_review",
            ),
            "failed_sync_count": await _count_where(db, EngineeringKnowledgeFederationSyncRun.status == "failed"),
        },
        "operations": await federation_operational_summary(db),
    }


async def _count(db: AsyncSession, column: Any) -> int:
    return int((await db.execute(select(func.count(column)))).scalar_one() or 0)


async def _count_where(db: AsyncSession, condition: Any) -> int:
    return int((await db.execute(select(func.count()).where(condition))).scalar_one() or 0)


__all__ = ["get_engineering_knowledge_federation_dashboard"]
