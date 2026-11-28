from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, SafeModeState
from app.models.runtime.incident_response import SAFE_MODE_ACTIVE
from app.time_utils import utc_now


async def _make_project(db: AsyncSession, *, name: str = "test-project") -> Project:
    project = Project(id=str(uuid.uuid4()), name=name, description="Test")
    db.add(project)
    await db.commit()
    return project


async def _activate(db: AsyncSession, *, user_id: str, reason: str, project_id: str | None = None,
                    incident_id: str | None = None) -> SafeModeState:
    state = SafeModeState(project_id=project_id, state=SAFE_MODE_ACTIVE, reason=reason, incident_id=incident_id,
                          activated_by=user_id, activated_at=utc_now(), block_new_runs=True)
    db.add(state)
    await db.commit()
    return state
