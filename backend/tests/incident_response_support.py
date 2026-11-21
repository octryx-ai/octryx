"""Shared helpers for the test_incident_response_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project
from app.models.agent.agent_chain import AgentChainTemplate
from app.models.project.task import Task
from app.models.runtime.flow_definition import FlowDefinition


def _uid() -> str:
    return str(uuid.uuid4())


# ── Fixtures ─────────────────────────────────────────────────────────────────


async def _make_project(db: AsyncSession, *, name: str = "test-project") -> Project:
    p = Project(id=_uid(), name=name, description="Test")
    db.add(p)
    await db.commit()
    return p


async def _make_flow(db: AsyncSession, *, project_id: str, created_by: str | None = None) -> FlowDefinition:
    f = FlowDefinition(
        id=_uid(), project_id=project_id, key=f"flow-{_uid()[:8]}",
        name="test-flow", is_active=True, created_by=created_by or _uid(),
    )
    db.add(f)
    await db.commit()
    return f


async def _make_agent_chain(db: AsyncSession, *, project_id: str, created_by: str | None = None) -> AgentChainTemplate:
    t = AgentChainTemplate(
        id=_uid(), project_id=project_id, name="test-chain",
        is_active=True, created_by=created_by or _uid(),
    )
    db.add(t)
    await db.commit()
    return t


async def _make_task(db: AsyncSession, *, project_id: str, owner_id: str | None = None) -> Task:
    t = Task(dispatch_binding="task_definition",
        id=_uid(), project_id=project_id, name="test-task",
        is_active=True, owner_id=owner_id or _uid(),
    )
    db.add(t)
    await db.commit()
    return t
