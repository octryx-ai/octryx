from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...db.lock_errors import is_sqlite_lock_error
from ...models import (
    AnalyticsDaily,
    ReportExport,
    Session,
    TeamMember,
    TeamProject,
    User,
)
from ...time_utils import ensure_utc, utc_now
from ..error_facts import error_text
from .metrics import (
    build_team_users,
    date_matches,
    group_session_ids_by_project,
    load_metric_bundle_for_date,
    summarize_metrics,
    team_session_ids_for_project,
)
from .reporting import (
    ALLOWED_REPORT_FORMATS,
    ALLOWED_REPORT_TYPES,
    analytics_rows_for_export,
    build_report_payload,
    payload_to_csv_bytes,
    text_to_pdf_bytes,
)
from .serialization import serialize_analytics_daily, serialize_report_export

logger = logging.getLogger(__name__)

ANALYTICS_INTERVAL_SECONDS = 60
REPORT_EXPORT_DIR = Path(__file__).resolve().parents[3] / "data" / "report_exports"


async def _upsert_analytics_row(
    db: AsyncSession,
    *,
    target_date: date,
    project_id: str | None,
    team_id: str | None,
    metrics: dict[str, Any],
) -> AnalyticsDaily:
    stmt = select(AnalyticsDaily).where(AnalyticsDaily.date == target_date)
    if project_id is None:
        stmt = stmt.where(AnalyticsDaily.project_id.is_(None))
    else:
        stmt = stmt.where(AnalyticsDaily.project_id == project_id)
    if team_id is None:
        stmt = stmt.where(AnalyticsDaily.team_id.is_(None))
    else:
        stmt = stmt.where(AnalyticsDaily.team_id == team_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = AnalyticsDaily(id=str(uuid.uuid4()), project_id=project_id, team_id=team_id, date=target_date)
        db.add(row)
    for key, value in metrics.items():
        if key == "cost_by_provider":
            row.cost_by_provider = value
        else:
            setattr(row, key, value)
    row.created_at = utc_now()
    await db.flush()
    return row


async def aggregate_analytics_for_date(db: AsyncSession, *, target_date: date) -> int:
    sessions = (await db.execute(select(Session).where(Session.project_id.is_not(None)))).scalars().all()
    sessions = [session for session in sessions if date_matches(session.started_at, target_date)]
    session_ids = {session.id for session in sessions}
    if not session_ids:
        return 0

    bundle = await load_metric_bundle_for_date(
        db,
        target_date=target_date,
        session_ids=session_ids,
        sessions=sessions,
    )

    session_ids_by_project = group_session_ids_by_project(sessions)
    team_projects = (await db.execute(select(TeamProject))).scalars().all()
    team_members = (await db.execute(select(TeamMember))).scalars().all()
    team_users = build_team_users(team_members)

    upserts = 0
    for project_id, scoped_session_ids in session_ids_by_project.items():
        metrics = summarize_metrics(bundle, session_ids=scoped_session_ids)
        await _upsert_analytics_row(db, target_date=target_date, project_id=project_id, team_id=None, metrics=metrics)
        upserts += 1
        for team_project in team_projects:
            if team_project.project_id != project_id:
                continue
            team_session_ids = team_session_ids_for_project(
                sessions,
                project_id=project_id,
                team_user_ids=team_users.get(team_project.team_id, set()),
            )
            team_metrics = summarize_metrics(bundle, session_ids=team_session_ids)
            await _upsert_analytics_row(
                db,
                target_date=target_date,
                project_id=project_id,
                team_id=team_project.team_id,
                metrics=team_metrics,
            )
            upserts += 1
    await db.commit()
    return upserts


async def aggregate_due_analytics(db: AsyncSession) -> int:
    today = ensure_utc(utc_now()).date()
    affected = 0
    for target_date in (today - timedelta(days=1), today):
        affected += await aggregate_analytics_for_date(db, target_date=target_date)
    return affected


async def list_analytics_daily(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    team_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(AnalyticsDaily).order_by(AnalyticsDaily.date.desc())
    if project_id:
        stmt = stmt.where(AnalyticsDaily.project_id == project_id)
    if team_id:
        stmt = stmt.where(AnalyticsDaily.team_id == team_id)
    if date_from:
        stmt = stmt.where(AnalyticsDaily.date >= date_from)
    if date_to:
        stmt = stmt.where(AnalyticsDaily.date <= date_to)
    rows = (await db.execute(stmt.limit(max(1, min(limit, 365))))).scalars().all()
    return [serialize_analytics_daily(row) for row in rows]


async def create_report_export(
    db: AsyncSession,
    *,
    current_user: User,
    report_type: str,
    format: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_type = str(report_type or "").strip().lower()
    normalized_format = str(format or "").strip().lower()
    if normalized_type not in ALLOWED_REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported report_type")
    if normalized_format not in ALLOWED_REPORT_FORMATS:
        raise HTTPException(status_code=400, detail="Unsupported export format")
    row = ReportExport(
        id=str(uuid.uuid4()),
        created_by=current_user.id,
        report_type=normalized_type,
        format=normalized_format,
        status="pending",
    )
    row.parameters = parameters or {}
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return serialize_report_export(row)


async def list_report_exports(db: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        (await db.execute(select(ReportExport).order_by(ReportExport.created_at.desc()).limit(max(1, min(limit, 200)))))
        .scalars()
        .all()
    )
    return [serialize_report_export(row) for row in rows]


async def get_report_export(db: AsyncSession, report_export_id: str) -> ReportExport:
    row = await db.get(ReportExport, report_export_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report export not found")
    return row


async def process_pending_report_exports(db: AsyncSession) -> int:
    rows = (
        (
            await db.execute(
                select(ReportExport).where(ReportExport.status == "pending").order_by(ReportExport.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    REPORT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    processed = 0
    for row in rows:
        try:
            row.status = "running"
            await db.flush()
            analytics_rows = await analytics_rows_for_export(db, parameters=row.parameters)
            payload = build_report_payload(row.report_type, analytics_rows)
            if row.format == "json":
                file_bytes = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
            elif row.format == "csv":
                file_bytes = payload_to_csv_bytes(payload)
            else:
                summary_text = json.dumps(payload, indent=2, ensure_ascii=True)
                file_bytes = text_to_pdf_bytes(summary_text)
            file_path = REPORT_EXPORT_DIR / f"{row.id}.{row.format}"
            file_path.write_bytes(file_bytes)
            row.file_url = str(file_path)
            row.status = "completed"
            row.error = None
            row.completed_at = utc_now()
        except Exception as exc:
            row.status = "failed"
            row.error = error_text("report_export_failed", exc)
            row.completed_at = utc_now()
            logger.exception("Report export failed", extra={"report_export_id": row.id, "report_type": row.report_type})
        processed += 1
    await db.commit()
    return processed


class AnalyticsWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        interval_seconds: int = ANALYTICS_INTERVAL_SECONDS,
        startup_delay_seconds: int = 15,
    ):
        self._session_factory = session_factory
        self._interval_seconds = max(10, int(interval_seconds))
        self._startup_delay_seconds = max(0, int(startup_delay_seconds))
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self) -> None:
        if self._startup_delay_seconds:
            await asyncio.sleep(self._startup_delay_seconds)
        while True:
            try:
                async with self._session_factory() as db:
                    affected = await aggregate_due_analytics(db)
                    exports = await process_pending_report_exports(db)
                await asyncio.sleep(5 if affected or exports else self._interval_seconds)
            except asyncio.CancelledError:
                raise
            except OperationalError as exc:
                if is_sqlite_lock_error(exc):
                    logger.warning("Analytics worker skipped iteration after database lock", exc_info=exc)
                else:
                    logger.exception("Analytics worker loop failed")
                await asyncio.sleep(self._interval_seconds)
            except Exception:
                logger.exception("Analytics worker loop failed")
                await asyncio.sleep(self._interval_seconds)
