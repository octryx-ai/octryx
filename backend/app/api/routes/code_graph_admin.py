"""The code graph's backfill.

``POST /api/v1/admin/code-graph/backfill`` (platform admins, optional ``project_id``; a named Workspace that does not
exist is 404 ``project_not_found`` before anything is mirrored or audited): every active repository with a
remote is mirrored under ``code_mirror_root`` once and, unless its graph is disabled, indexed; the answer lists what
happened per repository.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import AuditLog, User
from ...services.access_control import require_existing_workspace
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user

router = APIRouter(tags=["code-graph"])


@router.post("/api/v1/admin/code-graph/backfill")
async def backfill_code_graph(body: dict[str, Any] | None = Body(default=None),
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not await is_global_admin(db, current_user.id):
        return JSONResponse({"state": "denied", "reason": "platform_admin_required"}, status_code=403)
    from ...services.code_intelligence.graph_refresh import backfill

    project_id = str((body or {}).get("project_id") or "").strip() or None
    await require_existing_workspace(db, project_id)
    results = await backfill(db, project_id=project_id)
    db.add(AuditLog(user_id=current_user.id, action="admin.code_graph_backfill", resource_type="code_graph",
                    resource_id=project_id or "all", details={"repositories": len(results)}))
    await db.commit()
    return {"repositories": results}
