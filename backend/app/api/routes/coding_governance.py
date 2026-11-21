"""Coding governance in one place. Transport only.

- ``GET  /api/v1/secure-work/workspaces/{project_id}/coding-rules``: the effective rules, read only;
- ``POST /api/v1/secure-work/coding-pipelines/checks/preview``: a change's evidence against the pipeline checks.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.secure_work.access import require_work_operator
from ...services.secure_work.coding.effective_rules import effective_rules
from ...services.secure_work.coding.pipeline_checks import preview_pipeline_checks
from ._secure_work_scope import require_secure_work_scope
from .secure_work_intake import authorize_workspace

router = APIRouter(
    prefix="/api/v1/secure-work", tags=["secure-work"], dependencies=[Depends(require_secure_work_scope)]
)


@router.get("/workspaces/{project_id}/coding-rules")
async def get_coding_rules(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await authorize_workspace(db, current_user, project_id)
    return await effective_rules(db, project_id)


@router.post("/coding-pipelines/checks/preview")
async def post_pipeline_checks_preview(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await require_work_operator(db, current_user)
    return await preview_pipeline_checks(db, payload=payload, current_user=current_user)
