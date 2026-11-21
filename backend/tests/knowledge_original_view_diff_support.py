"""Shared helpers for the test_knowledge_original_view_diff_* modules."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.main import app
from app.models.project.knowledge_evidence import KnowledgeSourceRevision
from app.services.auth import get_current_user
from app.services.knowledge.runtime import set_evidence_runtime
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

BASE = "/api/v1/workspaces"


FIRST = b"# Runbook\n\nThe Zurich datacenter hosts the primary cluster.\nFailover runs from Geneva.\n"


@pytest.fixture
def evidence_runtime():
    runtime, s3, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    try:
        yield runtime, s3, evidence_index
    finally:
        set_evidence_runtime(None)


@pytest.fixture
def as_user(db):
    def _install(user):
        app.dependency_overrides[get_current_user] = lambda: user

    yield _install
    app.dependency_overrides.pop(get_current_user, None)


async def _upload(client, workspace_id, *, payload=FIRST, source_key="runbook", media_type="text/markdown") -> dict:
    response = await client.post(
        f"{BASE}/{workspace_id}/knowledge/sources",
        files={"file": ("ignored.md", payload, media_type)},
        data={"source_key": source_key, "display_title": "Runbook"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _path(workspace_id, source_id, revision_id, suffix="original") -> str:
    return f"{BASE}/{workspace_id}/knowledge/sources/{source_id}/revisions/{revision_id}/{suffix}"


async def _set_revision(db, revision_id: str, **values) -> None:
    await db.execute(update(KnowledgeSourceRevision).where(KnowledgeSourceRevision.id == revision_id).values(**values))
    await db.commit()


async def _owner_and_source(client, db, as_user):
    workspace_id = await seed_workspace(db)
    owner = await fetch_user(db, await seed_member(db, workspace_id=workspace_id, role="admin"))
    as_user(owner)
    created = await _upload(client, workspace_id)
    return workspace_id, owner, created


def _code(response) -> str:
    return response.json()["detail"]["code"]
