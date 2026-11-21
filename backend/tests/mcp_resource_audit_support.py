"""Reads the governed MCP resource audit rows of one test workspace."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog
from app.services.mcp_resource_audit import MCP_RESOURCE_AUDIT_ACTION


async def _audit_rows(db, workspace) -> list[AuditLog]:
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.action == MCP_RESOURCE_AUDIT_ACTION)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )
        .scalars()
        .all()
    )
    return [row for row in rows if row.details.get("workspace_id") in {workspace.project.id, ""}]
