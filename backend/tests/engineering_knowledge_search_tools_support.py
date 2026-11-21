"""A published Java engineering pack and the tool context shared by the engineering pack tool tests."""

from __future__ import annotations

import uuid

from app.models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)
from app.services.engineering_knowledge.retrieval_index import rebuild_engineering_knowledge_retrieval_index
from app.tools.context import ToolContext


async def _create_published_java_pack(db) -> EngineeringKnowledgePackVersion:
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key="java-21-to-25-spring-boot-3.4-to-4.0.3",
        name="Java 21 to 25 / Spring Boot 3.4 to 4.0.3 Engineering Knowledge Pack",
        stack_key="java-spring",
        lifecycle_status="active",
        source_policy={"trust_tiers": ["official", "vendor"]},
        freshness_policy={"ttl_days": 30},
        is_active=True,
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack=pack,
        version=1,
        status="published",
        source_versions={"java": "21", "spring_boot": "3.4"},
        target_versions={"java": "25", "spring_boot": "4.0.3"},
        compatibility_facts={"stack_key": "java-spring"},
        manifest={
            "schema_version": 2,
            "evidence_ledger": [
                {
                    "fact_id": "spring-boot-4-java-25-fact",
                    "claim": "Spring Boot 4.0.3 migration requires exact Java 25 and BOM evidence.",
                    "coverage_areas": ["migration", "build_tooling"],
                    "source_key": "spring-boot-4-0-3-reference",
                    "source_uri": "https://docs.spring.io/spring-boot/4.0.3/reference/index.html",
                    "archive_path": "engineering-knowledge/test/evidence.json",
                    "usable_for_pack": True,
                },
                {
                    "fact_id": "spring-boot-4-runtime-fact",
                    "claim": "Use the Spring Boot 4.0.3 reference before changing runtime code.",
                    "coverage_areas": ["runtime_performance"],
                    "source_key": "spring-boot-4-0-3-reference",
                    "source_uri": "https://docs.spring.io/spring-boot/4.0.3/reference/index.html",
                    "archive_path": "engineering-knowledge/test/evidence.json",
                    "usable_for_pack": True,
                },
            ],
        },
        quality_status="passed",
        quality_report={"passed": True, "blockers": []},
    )
    source = EngineeringKnowledgePackSource(
        id=str(uuid.uuid4()),
        pack_version=version,
        source_key="spring-boot-4-0-3-reference",
        title="Spring Boot 4.0.3 Reference",
        source_uri="https://docs.spring.io/spring-boot/4.0.3/reference/index.html",
        source_type="documentation",
        trust_tier="official",
        version_label="4.0.3",
        checksum="sha256-test",
        fetch_status="fetched",
        freshness_status="fresh",
        evidence_archive_path="engineering-knowledge/test/evidence.json",
        source_metadata={
            "coordinate": "spring_boot",
            "target_version": "4.0.3",
            "source_audit": {
                "status": "accepted",
                "reason": "Fixture official source accepted.",
                "canonical_uri": "https://docs.spring.io/spring-boot/4.0.3/reference/index.html",
                "coverage_areas": ["api_reference"],
                "blockers": [],
            },
        },
    )
    item = EngineeringKnowledgePackItem(
        id=str(uuid.uuid4()),
        pack_version=version,
        source=source,
        item_key="spring-boot-4-runtime-baseline",
        title="Spring Boot 4 runtime baseline",
        summary="Spring Boot 4 requires a Java 25 migration review and exact BOM evidence.",
        content="Use the Spring Boot 4.0.3 reference and dependency BOM before changing runtime code.",
        tags=["java-spring", "migration", "dependency-management"],
        triggers=["spring boot 4", "bom"],
        version_scope={"target_versions": {"java": "25", "spring_boot": "4.0.3"}},
        retrieval_priority="high",
        retrieval_rank=10,
        item_metadata={
            "evidence": [
                {
                    "source_key": "spring-boot-4-0-3-reference",
                    "checksum": "sha256-test",
                    "evidence_archive_path": "engineering-knowledge/test/evidence.json",
                }
            ],
            "evidence_fact_ids": ["spring-boot-4-java-25-fact", "spring-boot-4-runtime-fact"],
        },
    )
    db.add_all([pack, version, source, item])
    await db.flush()
    await rebuild_engineering_knowledge_retrieval_index(db, pack_version_id=version.id)
    await db.commit()
    return version


def _context(db, tmp_path) -> ToolContext:
    return ToolContext(
        user_id="admin",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={},
        current_user_message="",
        db=db,
        workspace_root=str(tmp_path),
    )
