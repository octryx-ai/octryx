"""Runtime resolution asks among several repositories, takes the bound repository and blocks without an exact published pack."""

from __future__ import annotations

import uuid

import pytest

from app.models import CodeRepository, Project
from app.services.engineering_knowledge import resolve_engineering_runtime_context
from tests.services.engineering_knowledge.engineering_knowledge_runtime_resolution_support import (
    _java_spring,
    _write_spring_pom,
)


@pytest.mark.asyncio
async def test_runtime_resolution_takes_the_bound_repository_never_a_prompt_word(db, tmp_path):
    project = Project(id=str(uuid.uuid4()), name=f"fixture-{uuid.uuid4().hex[:8]}", is_active=True)
    acme_orders_root = tmp_path / "acme-orders-access-proxy"
    provenance_root = tmp_path / "provenance-live-repo"
    status_root = tmp_path / "status-live-repo"
    for repo_root in (acme_orders_root, provenance_root, status_root):
        _write_spring_pom(repo_root)
    db.add_all(
        [
            project,
            bound := CodeRepository(
                id=str(uuid.uuid4()),
                project_id=project.id,
                name="acme-orders-access-proxy",
                repo_root=str(acme_orders_root),
                is_active=True,
            ),
            CodeRepository(
                id=str(uuid.uuid4()),
                project_id=project.id,
                name="provenance-live-repo",
                repo_root=str(provenance_root),
                is_active=True,
            ),
            CodeRepository(
                id=str(uuid.uuid4()),
                project_id=project.id,
                name="status-live-repo",
                repo_root=str(status_root),
                is_active=True,
            ),
        ]
    )
    await db.commit()

    # Without a binding, three repositories are a closed clarification, whatever the request names.
    unbound = await resolve_engineering_runtime_context(db, target=_java_spring("4.0.3"), project_id=project.id)
    assert unbound.repository_resolution is not None and unbound.repository_resolution.repository is None
    assert {blocker["code"] for blocker in unbound.blockers} == {"ambiguous_repository"}

    resolution = await resolve_engineering_runtime_context(
        db, target=_java_spring("4.0.3"), project_id=project.id, repository_id=bound.id
    )
    assert resolution.repository_resolution is not None
    assert resolution.repository_resolution.repository is not None
    assert resolution.repository_resolution.repository.name == "acme-orders-access-proxy"
    assert resolution.repository_resolution.match_reason == "explicit repository id"


