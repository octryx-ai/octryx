"""Shared helpers for the test_data_classification_settings_* modules."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog, Project, User
from app.services.auth import create_access_token
from tests.knowledge_evidence_seed_support import seed_workspace

RERANKER = "bedrock_cohere_rerank35_v1"  # approved up to ``internal``


REMOTE_SPACE = "bedrock_titan2_1024_v1"  # approved up to ``internal``


def _route(project_id: str) -> str:
    return f"/api/v1/workspaces/{project_id}/data-classification"


def _seat_route(project_id: str) -> str:
    return f"/api/v1/workspaces/{project_id}/agent-gateway/seat-mode"


async def _bearer(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _admin_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


async def _workspace(db, config: dict | None = None) -> str:
    workspace_id = await seed_workspace(db)
    (await db.get(Project, workspace_id)).config = config or {}
    await db.commit()
    return workspace_id


async def _config(db, project_id: str) -> dict:
    project = await db.get(Project, project_id)
    await db.refresh(project)
    return dict(project.config or {})


async def _actions(db, resource_id: str) -> list[str]:
    rows = await db.execute(select(AuditLog.action).where(AuditLog.resource_id == resource_id))
    return list(rows.scalars())


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_RERANKER", RERANKER)
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_EMBEDDING_SPACE", REMOTE_SPACE)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")  # the reranker runtime builds its client here
    monkeypatch.setattr(get_settings(), "knowledge_default_data_classification", "none")
    return monkeypatch
