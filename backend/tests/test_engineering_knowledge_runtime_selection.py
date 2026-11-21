"""Runtime resolution asks among several repositories, takes the bound repository and blocks without an exact published pack."""

from __future__ import annotations

import uuid

import pytest

from app.models import CodeRepository, Project
from app.services.engineering_knowledge import resolve_engineering_runtime_context
from app.services.engineering_knowledge._runtime_types import EngineeringUpgradeTarget
from tests.engineering_knowledge_runtime_resolution_support import _java_spring, _write_spring_pom


@pytest.mark.asyncio
async def test_runtime_resolution_asks_when_several_repositories_are_in_scope(db, tmp_path):
    project = Project(id=str(uuid.uuid4()), name=f"fixture-{uuid.uuid4().hex[:8]}", is_active=True)
    repo_a_root = tmp_path / "acme-orders-api"
    repo_b_root = tmp_path / "acme-orders-service"
    _write_spring_pom(repo_a_root)
    _write_spring_pom(repo_b_root)
    db.add_all(
        [
            project,
            CodeRepository(
                id=str(uuid.uuid4()),
                project_id=project.id,
                name="acme-orders-api",
                repo_root=str(repo_a_root),
                is_active=True,
            ),
            CodeRepository(
                id=str(uuid.uuid4()),
                project_id=project.id,
                name="acme-orders-service",
                repo_root=str(repo_b_root),
                is_active=True,
            ),
        ]
    )
    await db.commit()

    resolution = await resolve_engineering_runtime_context(
        db,
        target=EngineeringUpgradeTarget(stack_key="java", target_versions={"java": "25"}),
        project_id=project.id,
    )

    assert resolution.is_ready is False
    assert {blocker["code"] for blocker in resolution.blockers} == {"ambiguous_repository"}
    assert resolution.repository_resolution is not None
    assert {candidate["name"] for candidate in resolution.repository_resolution.candidates} == {
        "acme-orders-api",
        "acme-orders-service",
    }
    assert "Which repository should be used?" in resolution.clarification_questions[0]
    assert "naming it in the chat does not select it" in resolution.clarification_questions[0]
    assert resolution.context_bundle()["state"] == "needs_clarification"


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


@pytest.mark.asyncio
async def test_runtime_resolution_blocks_when_no_exact_published_pack_exists(db, tmp_path):
    project = Project(id=str(uuid.uuid4()), name=f"fixture-{uuid.uuid4().hex[:8]}", is_active=True)
    repo_root = tmp_path / "acme-orders-access-proxy"
    _write_spring_pom(repo_root)
    db.add_all(
        [
            project,
            CodeRepository(
                id=str(uuid.uuid4()),
                project_id=project.id,
                name="acme-orders-access-proxy",
                repo_root=str(repo_root),
                is_active=True,
                config_json={"operation_policy": {"migration": True}},
            ),
        ]
    )
    await db.commit()

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.99"),
        project_id=project.id,
    )

    assert resolution.is_ready is False
    assert {blocker["code"] for blocker in resolution.blockers} == {"missing_engineering_knowledge_pack"}
    assert resolution.clarification_questions == []
    bundle = resolution.context_bundle()
    build_request = bundle["knowledge_build_request"]
    assert build_request["required"] is True
    assert build_request["requires_source_version_discovery"] is False
    assert build_request["tool_arguments"] == {
        "stack_key": "java-spring",
        "source_versions": {"java": "21", "spring_boot": "3.4.12"},
        "target_versions": {"java": "25", "spring_boot": "4.0.99"},
    }
    assert "from Spring Boot 3.4.12 to Spring Boot 4.0.99" in build_request["description"]
