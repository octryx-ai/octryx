"""Runtime resolution discovers local, global registered and Python repositories with their default packs under the migration policy."""

from __future__ import annotations

import uuid

import pytest

from app.models import (
    CodeRepository,
    EngineeringKnowledgePack,
    EngineeringKnowledgePackAssignment,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
    Project,
)
from app.services.engineering_knowledge import (
    ensure_default_python_engineering_knowledge_pack,
    resolve_engineering_runtime_context,
)
from app.services.engineering_knowledge._runtime_types import EngineeringUpgradeTarget
from app.services.engineering_knowledge.retrieval_index import rebuild_engineering_knowledge_retrieval_index
from tests.services.engineering_knowledge.engineering_knowledge_runtime_resolution_support import (
    _java_spring,
    _write_spring_pom,
)


def _write_python_project(repo_root) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / ".python-version").write_text("3.11\n", encoding="utf-8")
    (repo_root / "pyproject.toml").write_text(
        """
[project]
name = "demo-python"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
""".strip(),
        encoding="utf-8",
    )


async def _create_java_default_pack(db):
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key="java-25-spring-boot-4-0-3",
        name="Java 25 / Spring Boot 4.0.3 Engineering Knowledge Pack",
        stack_key="java-spring",
        lifecycle_status="active",
        is_active=True,
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack_id=pack.id,
        version=1,
        status="published",
        source_versions={"java": "21", "spring_boot": "3.4"},
        target_versions={"java": "25", "spring_boot": "4.0.3"},
        quality_status="passed",
        quality_report={"passed": True, "blockers": []},
        archive_root="engineering-knowledge/java-default/v1",
    )
    source = EngineeringKnowledgePackSource(
        id=str(uuid.uuid4()),
        pack_version_id=version.id,
        source_key="java-25-spring-boot-4.0.3-reference",
        title="Java 25 and Spring Boot 4.0.3 Reference",
        source_uri="https://docs.spring.io/spring-boot/reference/",
        source_type="html",
        trust_tier="official",
        fetch_status="fetched",
        freshness_status="fresh",
        checksum="sha256:default",
    )
    item = EngineeringKnowledgePackItem(
        id=str(uuid.uuid4()),
        pack_version_id=version.id,
        source_id=source.id,
        item_key="java-25-spring-boot-4.0.3-baseline",
        title="Java 25 and Spring Boot 4.0.3 baseline",
        summary="Use exact-version source-backed guidance before migration.",
        content="Default test pack content for runtime resolution.",
        tags=["java-spring", "migration"],
        retrieval_rank=10,
    )
    assignment = EngineeringKnowledgePackAssignment(
        id=str(uuid.uuid4()),
        pack_version_id=version.id,
        scope_type="global",
        stack_key="java-spring",
        assignment_status="active",
        assignment_policy={"manual_user_selection": False},
        priority=100,
    )
    db.add_all([pack, version, source, item, assignment])
    await db.flush()
    await rebuild_engineering_knowledge_retrieval_index(db, pack_version_id=version.id)
    await db.commit()
    return pack, version


@pytest.mark.asyncio
async def test_runtime_resolution_discovers_local_repository_from_allowed_root(db, tmp_path):
    await _create_java_default_pack(db)
    external_root = tmp_path / "externalrepos"
    repo_root = external_root / "acme-orders-access-proxy"
    _write_spring_pom(repo_root)

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.3"),
        local_search_roots=[str(external_root)],
    )

    assert resolution.is_ready is True
    assert resolution.repository_resolution is not None
    assert resolution.repository_resolution.repository is not None
    assert resolution.repository_resolution.repository.provider == "local_discovered"
    assert resolution.repository_resolution.repository.name == "acme-orders-access-proxy"
    assert resolution.repository_resolution.detected_stack_key == "java-spring"
    assert resolution.request.source_versions == {"java": "21", "spring_boot": "3.4.12"}
    assert resolution.pack_resolution is not None
    assert resolution.pack_resolution.pack.key == "java-25-spring-boot-4-0-3"


@pytest.mark.asyncio
async def test_runtime_resolution_blocks_registered_repository_when_migration_policy_disabled(db, tmp_path):
    project = Project(id=str(uuid.uuid4()), name=f"migration-policy-{uuid.uuid4().hex[:8]}", is_active=True)
    repo_root = tmp_path / "spring-petclinic-rest"
    _write_spring_pom(repo_root)
    repo = CodeRepository(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="spring-petclinic-rest",
        repo_root=str(repo_root),
        provider="local",
        is_active=True,
        config_json={"operation_policy": {"migration": False}},
    )
    db.add_all([project, repo])
    await db.commit()

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.3"),
        project_id=project.id,
    )

    assert resolution.is_ready is False
    assert resolution.repository_resolution is not None
    assert resolution.repository_resolution.repository is not None
    assert resolution.repository_resolution.repository.id == repo.id
    assert {item["code"] for item in resolution.blockers} == {"repository_migration_disabled"}
    assert resolution.pack_resolution is None


@pytest.mark.asyncio
async def test_runtime_resolution_can_use_global_registered_repository_with_project_context(db, tmp_path):
    await _create_java_default_pack(db)
    project = Project(id=str(uuid.uuid4()), name=f"fixture-{uuid.uuid4().hex[:8]}", is_active=True)
    repo_root = tmp_path / "spring-petclinic-rest-openrewrite-lab"
    _write_spring_pom(repo_root)
    repo = CodeRepository(
        id=str(uuid.uuid4()),
        project_id=None,
        name="spring-petclinic-rest",
        repo_root=str(repo_root),
        provider="local",
        is_active=True,
        config_json={"operation_policy": {"migration": True}},
    )
    db.add_all([project, repo])
    await db.commit()

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.3"),
        project_id=project.id,
    )

    assert resolution.is_ready is True
    assert resolution.repository_resolution is not None
    assert resolution.repository_resolution.repository is not None
    assert resolution.repository_resolution.repository.id == repo.id
    assert resolution.repository_resolution.detected_stack_key == "java-spring"
    assert resolution.pack_resolution is not None


@pytest.mark.asyncio
async def test_runtime_resolution_discovers_python_repository_and_default_pack(db, tmp_path):
    await ensure_default_python_engineering_knowledge_pack(db, archive_base_path=tmp_path)
    await db.commit()
    external_root = tmp_path / "externalrepos"
    repo_root = external_root / "demo-python"
    _write_python_project(repo_root)

    resolution = await resolve_engineering_runtime_context(
        db,
        target=EngineeringUpgradeTarget(stack_key="python", target_versions={"python": "3.12"}),
        local_search_roots=[str(external_root)],
    )

    assert resolution.is_ready is True
    assert resolution.repository_resolution is not None
    assert resolution.repository_resolution.repository is not None
    assert resolution.repository_resolution.repository.provider == "local_discovered"
    assert resolution.repository_resolution.detected_stack_key == "python"
    assert resolution.request.source_versions == {"python": "3.11"}
    assert resolution.pack_resolution is not None
    assert resolution.pack_resolution.pack.key == "python-3-12-engineering-quality"
    assert resolution.items
    assert {item["source_key"] for item in resolution.items} >= {"python-3-12-docs", "python-3-12-whats-new"}
