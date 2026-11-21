from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.coding_discipline.helpers import _coerce_utc_bounds
from app.services.coding_discipline.stats_buckets import BucketBook, accumulate_trace
from app.services.coding_discipline.stats_helpers import (
    build_rows_out,
    build_summary,
    collect_target_and_provider_names,
    init_discipline_summary,
    load_provider_maps,
)

from ...models import Session as AgentSession
from ...models import TurnTrace


async def coding_discipline_stats(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: str | None = None,
    limit: int = 50,
    recommend_models_func: Callable[..., Awaitable[dict[str, dict[str, Any]]]],
) -> dict[str, Any]:
    start_dt, end_dt = _coerce_utc_bounds(date_from=date_from, date_to=date_to)
    stmt = (
        select(TurnTrace, AgentSession)
        .join(AgentSession, AgentSession.id == TurnTrace.session_id)
        .order_by(TurnTrace.created_at.desc())
    )
    if start_dt is not None:
        stmt = stmt.where(TurnTrace.created_at >= start_dt)
    if end_dt is not None:
        stmt = stmt.where(TurnTrace.created_at < end_dt)
    if project_id:
        stmt = stmt.where(AgentSession.project_id == project_id)
    rows = (await db.execute(stmt)).all()

    target_ids, provider_names = collect_target_and_provider_names(rows)
    runtime_targets, providers_by_name, providers_by_id = await load_provider_maps(
        db,
        target_ids=target_ids,
        provider_names=provider_names,
    )

    book = BucketBook(
        runtime_targets=runtime_targets,
        providers_by_name=providers_by_name,
        providers_by_id=providers_by_id,
        discipline_summary=init_discipline_summary(),
    )
    for trace, _session in rows:
        accumulate_trace(book, trace)

    rows_out = build_rows_out(book.buckets)
    recommendations = await recommend_models_func(
        db,
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        min_turns=2,
        stats_payload={"rows": rows_out},
    )
    summary = build_summary(book.discipline_summary)
    return {
        "filters": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "project_id": project_id,
            "limit": max(1, min(limit, 200)),
        },
        "summary": summary,
        "rows": rows_out[: max(1, min(limit, 200))],
        "recommendations": recommendations,
    }
