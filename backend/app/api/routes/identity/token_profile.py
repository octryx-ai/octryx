"""``/api/v1/workflow-runs/{run_id}/token-profile``: where the run's tokens went and where they could be saved. Readable
with the run's read access."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.observability.token_profile.read_model import run_token_profile
from ....services.workflow_runs.access import require_run
from ....services.workflow_runs.records import WorkflowRunError

router = APIRouter()


@router.get("/{run_id}/token-profile")
async def get_token_profile(run_id: str, current_user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    try:
        run = await require_run(db, run_id, current_user)
    except WorkflowRunError as error:
        raise HTTPException(status_code=error.status_code,
                            detail={"code": error.code, "message": str(error)}) from error
    return await run_token_profile(db, run)
