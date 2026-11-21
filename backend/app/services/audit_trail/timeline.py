"""Observability → Audit log (O5): who changed what, administrative changes only, paged and exportable."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User
from ...time_utils import ensure_utc, utc_now
from ..redaction_policy import redact_secret_payload
from .categories import CATEGORIES, category_expression

WINDOW_DAYS = (1, 7, 30, 90)
DEFAULT_WINDOW_DAYS = 30
MAX_PAGE_SIZE = 100
MAX_EXPORT_ROWS = 5000
EXPORTED_ACTION = "observability.audit.exported"


def _statement(*, window_days: int, category: str | None, query: str | None):
    category_column = category_expression().label("category")
    statement = (
        select(AuditLog, User.username, category_column)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.created_at >= utc_now() - timedelta(days=window_days), category_column.is_not(None))
    )
    if category in CATEGORIES:
        statement = statement.where(category_column == category)
    needle = (query or "").strip().lower()
    if needle:
        pattern = f"%{needle}%"
        statement = statement.where(or_(
            func.lower(func.coalesce(User.username, "")).like(pattern),
            func.lower(AuditLog.action).like(pattern),
            func.lower(func.coalesce(AuditLog.resource_type, "")).like(pattern),
            func.lower(func.coalesce(AuditLog.resource_id, "")).like(pattern),
        ))
    return statement


def _serialize(row: Any) -> dict[str, Any]:
    log: AuditLog = row[0]
    details = log.details if isinstance(log.details, dict) else {}
    return {
        "id": log.id,
        "time": ensure_utc(log.created_at).isoformat() if log.created_at else None,
        "actor": row.username or log.user_id,
        "change": log.action,
        "object": " · ".join(part for part in (log.resource_type, log.resource_id) if part) or None,
        "category": row.category,
        "ip_address": log.ip_address,
        "details": redact_secret_payload(details),
    }


async def list_audit(
    db: AsyncSession,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    category: str | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    window_days = window_days if window_days in WINDOW_DAYS else DEFAULT_WINDOW_DAYS
    page, page_size = max(1, page), max(1, min(MAX_PAGE_SIZE, page_size))
    statement = _statement(window_days=window_days, category=category, query=query)
    total = int((await db.execute(select(func.count()).select_from(statement.subquery()))).scalar() or 0)
    rows = (await db.execute(statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                             .limit(page_size).offset((page - 1) * page_size))).all()
    return {"window_days": window_days, "categories": list(CATEGORIES), "page": page, "page_size": page_size,
            "total": total, "items": [_serialize(row) for row in rows]}


async def export_audit_csv(
    db: AsyncSession, *, viewer_id: str, window_days: int, category: str | None, query: str | None,
) -> str:
    """The filtered rows as CSV (at most ``MAX_EXPORT_ROWS``); the export itself is audited."""
    window_days = window_days if window_days in WINDOW_DAYS else DEFAULT_WINDOW_DAYS
    rows = (await db.execute(_statement(window_days=window_days, category=category, query=query)
                             .order_by(AuditLog.created_at.desc()).limit(MAX_EXPORT_ROWS))).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["time", "actor", "category", "change", "object", "ip_address", "details"])
    for row in rows:
        item = _serialize(row)
        writer.writerow([item["time"], item["actor"], item["category"], item["change"], item["object"] or "",
                         item["ip_address"] or "", json.dumps(item["details"], default=str)])
    db.add(AuditLog(user_id=viewer_id, action=EXPORTED_ACTION, resource_type="audit_log",
                    details={"rows": len(rows), "window_days": window_days, "category": category or "all"}))
    await db.commit()
    return buffer.getvalue()


__all__ = ["DEFAULT_WINDOW_DAYS", "export_audit_csv", "list_audit"]
