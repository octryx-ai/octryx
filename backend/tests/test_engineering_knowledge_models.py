from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackAssignment,
    EngineeringKnowledgePackBuildRun,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
    Project,
)
from app.services.engineering_knowledge import build_source_archive_paths


@pytest.mark.asyncio
async def test_engineering_knowledge_pack_persists_source_target_versions_and_evidence(db):
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key="java-21-to-25",
        name="Java 21 to 25 Migration",
        stack_key="java",
        source_policy={"trust_tiers": ["official", "vendor"]},
        freshness_policy={"ttl_days": 30},
        retrieval_policy={"context_budget_tokens": 12_000},
        toolchain_policy={"recipes": ["org.openrewrite.java.migrate.UpgradeToJava25"]},
        resolution_policy={"ask_user_on_ambiguity": True},
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack=pack,
        version=1,
        status="draft",
        source_versions={"java": "21"},
        target_versions={"java": "25"},
        archive_root="engineering-knowledge/java-21-to-25/v1",
        quality_status="passed",
        quality_report={"official_sources": 2},
    )
    paths = build_source_archive_paths(pack_slug=pack.key, pack_version=version.version, source_key="oracle-java-25-api")
    source = EngineeringKnowledgePackSource(
        id=str(uuid.uuid4()),
        pack_version=version,
        source_key="oracle-java-25-api",
        title="Java 25 API Documentation",
        source_uri="https://docs.oracle.com/en/java/javase/25/docs/api/index.html",
        source_type="javadoc",
        trust_tier="official",
        version_label="25",
        checksum="sha256:test",
        fetch_status="fetched",
        freshness_status="fresh",
        raw_archive_path=paths.raw,
        parsed_archive_path=paths.parsed,
        evidence_archive_path=paths.evidence,
    )
    item = EngineeringKnowledgePackItem(
        id=str(uuid.uuid4()),
        pack_version=version,
        source=source,
        item_key="java-http-client-compatibility",
        title="Java HTTP Client compatibility",
        content="Use the Java standard HttpClient API available in Java 25.",
        tags=["java", "http-client", "migration"],
        version_scope={"from": "21", "to": "25"},
        retrieval_priority="high",
        retrieval_rank=10,
    )
    db.add_all([pack, version, source, item])
    await db.commit()

    loaded = (
        await db.execute(
            select(EngineeringKnowledgePack)
            .options(
                selectinload(EngineeringKnowledgePack.versions).selectinload(EngineeringKnowledgePackVersion.sources),
                selectinload(EngineeringKnowledgePack.versions).selectinload(EngineeringKnowledgePackVersion.items),
            )
            .where(EngineeringKnowledgePack.key == "java-21-to-25")
        )
    ).scalar_one()

    loaded_version = loaded.versions[0]
    assert loaded_version.source_versions == {"java": "21"}
    assert loaded_version.target_versions == {"java": "25"}
    assert loaded_version.sources[0].raw_archive_path.endswith("/raw")
    assert loaded_version.items[0].version_scope == {"from": "21", "to": "25"}


@pytest.mark.asyncio
async def test_engineering_knowledge_assignment_and_builder_run_are_auditable(db):
    project = Project(id=str(uuid.uuid4()), name=f"engineering-knowledge-{uuid.uuid4().hex[:8]}", config={})
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key="spring-boot-34-to-403",
        name="Spring Boot 3.4 to 4.0.3 Migration",
        stack_key="java-spring",
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack=pack,
        version=1,
        status="draft",
        source_versions={"spring_boot": "3.4.x"},
        target_versions={"spring_boot": "4.0.3"},
    )
    assignment = EngineeringKnowledgePackAssignment(
        id=str(uuid.uuid4()),
        pack_version=version,
        scope_type="workspace",
        scope_id=project.id,
        workspace=project,
        stack_key="java-spring",
        assignment_policy={"default_for_stack": True},
    )
    run = EngineeringKnowledgePackBuildRun(
        id=str(uuid.uuid4()),
        pack=pack,
        pack_version=version,
        prompt="Erstelle ein Knowledge Pack um von Spring Boot 3.4 auf Spring Boot 4.0.3 zu migrieren.",
        stack_key="java-spring",
        source_versions={"spring_boot": "3.4.x"},
        target_versions={"spring_boot": "4.0.3"},
        status="validated",
        source_plan={"required_sources": ["spring-boot-reference", "spring-boot-migration-guide"]},
        acquisition_policy={"allow_community_sources": False},
        quality_report={"version_exactness": "passed"},
        publish_decision="requires_approval",
        approval_status="pending",
    )
    db.add_all([project, pack, version, assignment, run])
    await db.commit()

    loaded_run = (
        await db.execute(
            select(EngineeringKnowledgePackBuildRun)
            .options(
                selectinload(EngineeringKnowledgePackBuildRun.pack_version).selectinload(
                    EngineeringKnowledgePackVersion.assignments
                )
            )
            .where(EngineeringKnowledgePackBuildRun.id == run.id)
        )
    ).scalar_one()

    assert loaded_run.target_versions == {"spring_boot": "4.0.3"}
    assert loaded_run.publish_decision == "requires_approval"
    assert loaded_run.pack_version.assignments[0].workspace_id == project.id


def test_engineering_knowledge_archive_paths_are_deterministic_and_contained():
    paths = build_source_archive_paths(
        pack_slug="../Java 21 -> 25",
        pack_version="1",
        source_key="../../Oracle Java 25 API",
    )

    assert paths.source_root == "engineering-knowledge/Java-21-25/v1/sources/Oracle-Java-25-API"
    assert paths.raw == f"{paths.source_root}/raw"
    assert paths.parsed == f"{paths.source_root}/parsed"
    assert paths.evidence == f"{paths.source_root}/evidence"
    assert ".." not in paths.source_root.split("/")
