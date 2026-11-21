"""Runtime resolution selects exact published packs, injects indexed pack facts and skips stale or pending-review packs."""

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
from app.services.engineering_knowledge import resolve_engineering_runtime_context
from app.services.engineering_knowledge.retrieval_index import rebuild_engineering_knowledge_retrieval_index
from app.services.engineering_knowledge.runtime_prompt_renderer import resolve_engineering_knowledge_runtime_prompt
from tests.engineering_knowledge_runtime_resolution_support import (
    _java_spring,
    _write_spring_pom,
)


def _build_pack_and_version(version_status: str) -> tuple[EngineeringKnowledgePack, EngineeringKnowledgePackVersion]:
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key=f"java-21-to-25-spring-boot-34-to-403-{uuid.uuid4().hex[:8]}",
        name="Java 21 to 25 / Spring Boot 3.4 to 4.0.3 Engineering Knowledge Pack",
        stack_key="java-spring",
        lifecycle_status="active",
        retrieval_policy={"default_context_budget_tokens": 12000},
        is_active=True,
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack_id=pack.id,
        version=1,
        status=version_status,
        source_versions={"java": "21", "spring_boot": "3.4"},
        target_versions={"java": "25", "spring_boot": "4.0.3"},
        manifest={
            "schema_version": 2,
            "evidence_ledger": [
                {
                    "fact_id": "spring-boot-4-runtime-fact",
                    "claim": "Spring Boot 4.0.3 requires source-backed runtime migration review.",
                    "coverage_areas": ["migration", "runtime_performance"],
                    "source_key": "spring-boot-4.0.3-reference",
                    "source_uri": "https://docs.spring.io/spring-boot/reference/",
                    "archive_path": "engineering-knowledge/java/v1/sources/parsed.md",
                    "usable_for_pack": True,
                }
            ],
        },
        quality_status="passed",
        quality_report={"passed": True, "blockers": []},
        archive_root="engineering-knowledge/java/v1",
    )
    return pack, version


def _build_source_and_item(
    version: EngineeringKnowledgePackVersion, freshness_status: str
) -> tuple[EngineeringKnowledgePackSource, EngineeringKnowledgePackItem]:
    source = EngineeringKnowledgePackSource(
        id=str(uuid.uuid4()),
        pack_version_id=version.id,
        source_key="spring-boot-4.0.3-reference",
        title="Spring Boot 4.0.3 Reference",
        source_uri="https://docs.spring.io/spring-boot/reference/",
        source_type="html",
        trust_tier="official",
        version_label="4.0.3",
        fetch_status="fetched",
        freshness_status=freshness_status,
        checksum="sha256:test",
        raw_archive_path="engineering-knowledge/java/v1/sources/raw.html",
        parsed_archive_path="engineering-knowledge/java/v1/sources/parsed.md",
        evidence_archive_path="engineering-knowledge/java/v1/sources/evidence.json",
        source_metadata={
            "source_audit": {
                "status": "accepted",
                "canonical_uri": "https://docs.spring.io/spring-boot/reference/",
                "coverage_areas": ["migration", "runtime_performance"],
            }
        },
    )
    item = EngineeringKnowledgePackItem(
        id=str(uuid.uuid4()),
        pack_version_id=version.id,
        source_id=source.id,
        item_key="spring-boot-4-runtime-baseline",
        title="Spring Boot 4 runtime baseline",
        summary="Spring Boot 4 requires the Spring Framework 7 baseline.",
        content="Use Spring Boot 4.0.3 exact-version reference material before changing application code.",
        tags=["java-spring", "migration"],
        triggers=["spring boot 4", "runtime migration"],
        item_metadata={"evidence_fact_ids": ["spring-boot-4-runtime-fact"]},
        retrieval_priority="high",
        retrieval_rank=10,
    )
    return source, item


async def _create_project_repo_and_pack(
    db,
    tmp_path,
    *,
    freshness_status: str = "fresh",
    version_status: str = "published",
    create_assignment: bool = True,
):
    project = Project(id=str(uuid.uuid4()), name=f"fixture-{uuid.uuid4().hex[:8]}", is_active=True)
    repo_root = tmp_path / "acme-orders-access-proxy"
    _write_spring_pom(repo_root)
    repo = CodeRepository(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="acme-orders-access-proxy",
        repo_root=str(repo_root),
        provider="local",
        is_active=True,
        config_json={"operation_policy": {"migration": True}},
    )
    pack, version = _build_pack_and_version(version_status)
    source, item = _build_source_and_item(version, freshness_status)
    objects = [project, repo, pack, version, source, item]
    if create_assignment:
        objects.append(
            EngineeringKnowledgePackAssignment(
                id=str(uuid.uuid4()),
                pack_version_id=version.id,
                scope_type="global",
                stack_key="java-spring",
                assignment_status="active",
                assignment_policy={"manual_user_selection": False},
                priority=100,
            )
        )
    db.add_all(objects)
    await db.flush()
    if version_status == "published":
        await rebuild_engineering_knowledge_retrieval_index(db, pack_version_id=version.id)
    await db.commit()
    return project, repo, pack, version, source, item


@pytest.mark.asyncio
async def test_runtime_resolution_selects_repository_and_published_exact_pack(db, tmp_path):
    project, repo, pack, version, source, _item = await _create_project_repo_and_pack(db, tmp_path)

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.3"),
        project_id=project.id,
        max_items=4,
        budget_tokens=1000,
    )

    assert resolution.is_ready is True
    assert resolution.repository_resolution is not None
    assert resolution.repository_resolution.repository.id == repo.id
    assert resolution.repository_resolution.detected_stack_key == "java-spring"
    assert resolution.request.source_versions == {"java": "21", "spring_boot": "3.4.12"}
    assert resolution.pack_resolution is not None
    assert resolution.pack_resolution.pack.id == pack.id
    assert resolution.pack_resolution.pack_version.id == version.id
    assert resolution.pack_resolution.assignment is not None
    assert resolution.items[0]["source_id"] == source.id

    bundle = resolution.context_bundle()
    assert bundle["repository"]["name"] == "acme-orders-access-proxy"
    assert bundle["engineering_knowledge_pack"]["version_id"] == version.id
    assert bundle["retrieval"]["freshness_status"] == {"fresh": 1}
    assert bundle["retrieval"]["source_ids"] == [source.id]
    assert bundle["project_knowledge"]["source"] == "project_knowledge_base"
    assert bundle["engineering_pack_retrieval"]["facts"][0]["fact_id"] == "spring-boot-4-runtime-fact"
    assert (
        bundle["engineering_pack_retrieval"]["sources"][0]["canonical_uri"]
        == "https://docs.spring.io/spring-boot/reference/"
    )


@pytest.mark.asyncio
async def test_runtime_prompt_injects_indexed_engineering_pack_facts_and_sources(db, tmp_path):
    project, *_ = await _create_project_repo_and_pack(db, tmp_path)

    unselected_prompt, unselected_metadata = await resolve_engineering_knowledge_runtime_prompt(
        db=db,
        project_id=project.id,
        session_metadata={},
    )
    assert (unselected_prompt, unselected_metadata) == ("", {})

    # A run that resolved its target hands the resolution to its turns; the prompt renders it as is.
    resolved = await resolve_engineering_runtime_context(db, target=_java_spring("4.0.3"), project_id=project.id)
    prompt, metadata = await resolve_engineering_knowledge_runtime_prompt(
        db=db,
        project_id=project.id,
        session_metadata={"parent_engineering_knowledge_runtime_resolution": resolved.context_bundle()},
    )

    assert metadata["engineering_pack_retrieval"]["facts"][0]["fact_id"] == "spring-boot-4-runtime-fact"
    assert "Source boundary: project Knowledge contains internal facts" in prompt
    assert "Retrieved Engineering Pack facts:" in prompt
    assert "spring-boot-4-runtime-fact" in prompt
    assert "Retrieved Engineering Pack sources:" in prompt
    assert "https://docs.spring.io/spring-boot/reference/" in prompt


@pytest.mark.asyncio
async def test_runtime_resolution_blocks_stale_assigned_pack(db, tmp_path):
    project, *_ = await _create_project_repo_and_pack(db, tmp_path, freshness_status="stale")

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.3"),
        project_id=project.id,
    )

    assert resolution.is_ready is False
    assert {blocker["code"] for blocker in resolution.blockers} == {"stale_engineering_knowledge_pack"}
    assert resolution.source_freshness_counts == {"stale": 1}
    assert resolution.clarification_questions == []
    assert resolution.context_bundle()["knowledge_build_request"]["required"] is True


@pytest.mark.asyncio
async def test_runtime_resolution_does_not_inject_pending_review_pack(db, tmp_path):
    project, *_ = await _create_project_repo_and_pack(db, tmp_path, version_status="pending_review")

    resolution = await resolve_engineering_runtime_context(
        db,
        target=_java_spring("4.0.3"),
        project_id=project.id,
    )

    assert resolution.is_ready is False
    assert {blocker["code"] for blocker in resolution.blockers} == {"missing_engineering_knowledge_pack"}
    assert resolution.pack_resolution is not None
    assert resolution.pack_resolution.pack_version is None
    assert resolution.items == []
