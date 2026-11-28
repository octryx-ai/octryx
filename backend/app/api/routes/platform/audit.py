from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import AuditLog, UsageEvent, User
from ....services.audit_trail.workspace_scope import owner_known
from ....services.auth.admin_principal import get_current_admin_user
from ....time_utils import utc_now

# Both reads are platform-wide (every user's audit rows incl. IP, the whole platform's spend), so
# only a global admin may read them; no Workspace-scoped audit or usage read exists.
router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit")
async def list_audit_logs(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    action: str | None = None,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog).where(owner_known())
    if action:
        # Escape LIKE wildcards to prevent SQL injection via pattern manipulation
        escaped_action = action.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(AuditLog.action.ilike(f"%{escaped_action}%", escape="\\"))
    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": log_row.id,
            "user_id": log_row.user_id,
            "session_id": log_row.session_id,
            "action": log_row.action,
            "resource_type": log_row.resource_type,
            "resource_id": log_row.resource_id,
            "details": log_row.details,
            "ip_address": log_row.ip_address,
            "created_at": log_row.created_at.isoformat(),
        }
        for log_row in logs
    ]


@router.get("/usage")
async def get_usage(
    days: int = Query(default=7, le=90),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    since = utc_now() - timedelta(days=days)

    result = await db.execute(
        select(
            func.count(UsageEvent.id),
            func.sum(UsageEvent.tokens_in),
            func.sum(UsageEvent.tokens_out),
            func.sum(UsageEvent.cost),
        ).where(UsageEvent.created_at >= since)
    )
    row = result.one()

    result2 = await db.execute(
        select(
            UsageEvent.model,
            func.count(UsageEvent.id),
            func.sum(UsageEvent.tokens_in),
            func.sum(UsageEvent.tokens_out),
        )
        .where(UsageEvent.created_at >= since)
        .group_by(UsageEvent.model)
    )
    by_model = [
        {"model": r[0], "requests": r[1], "tokens_in": r[2] or 0, "tokens_out": r[3] or 0} for r in result2.all()
    ]

    return {
        "period_days": days,
        "total_requests": row[0] or 0,
        "total_tokens_in": row[1] or 0,
        "total_tokens_out": row[2] or 0,
        "total_cost": float(row[3] or 0),
        "by_model": by_model,
    }
