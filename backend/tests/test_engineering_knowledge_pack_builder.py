"""Structured pack requests carry exact versions and a derived stack, and a draft pack is built from archived fixture sources."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import EngineeringKnowledgePackItem, EngineeringKnowledgePackSource
from app.services.engineering_knowledge import (
    PACK_BUILD_NOT_REQUESTED,
    build_engineering_knowledge_pack_draft,
    pack_build_request_from_fields,
)


def test_structured_pack_request_carries_exact_versions_and_derived_stack():
    request = pack_build_request_from_fields(
        {
            "source_versions": {"java": "21", "spring_boot": "3.4"},
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
        }
    )

    assert request.is_ready is True
    assert request.stack_key == "java-spring"
    assert request.pack_key == "java-21-to-25-spring-boot-3.4-to-4.0.3"
    assert request.prompt == (
        "Build an Engineering Knowledge Pack to migrate from Java 21 to Java 25 "
        "and from Spring Boot 3.4 to Spring Boot 4.0.3."
    )


def test_pack_request_without_fields_is_not_requested_and_bad_fields_are_blockers():
    not_requested = pack_build_request_from_fields({"prompt": "Erstelle ein Knowledge Pack von Java 21 auf 25."})
    assert not_requested.is_pack_build_request is False
    assert [blocker["code"] for blocker in not_requested.blockers] == [PACK_BUILD_NOT_REQUESTED]

    target_only = pack_build_request_from_fields({"target_versions": {"java": "25"}})
    assert target_only.is_pack_build_request is True
    assert [blocker["code"] for blocker in target_only.blockers] == ["missing_source_versions"]

    invalid = pack_build_request_from_fields(
        {"stack_key": "cobol", "source_versions": {"java": "latest"}, "target_versions": {"node": "22"}}
    )
    assert {blocker["code"] for blocker in invalid.blockers} == {
        "invalid_versions",
        "unsupported_stack_key",
        "missing_source_target_versions",
    }


def _write_java_25_fixture_sources(tmp_path) -> dict:
    """Write the six archived Java 25 fixture sources; return them keyed by source key."""
    api_source = tmp_path / "java-api.md"
    api_source.write_text(
        "# Java 25 API\n\n"
        "- Java 25 API features include module imports and compact source files for developer ergonomics.\n"
        "- Java 25 security APIs include key derivation and crypto-related platform changes.\n",
        encoding="utf-8",
    )
    release_source = tmp_path / "java-release-notes.md"
    release_source.write_text(
        "# Java 25 Release Notes\n\n"
        "- Java 25 release notes cover runtime performance, JFR profiling, AOT behavior, and GC changes for migrated services.\n"
        "- Java 25 release notes also cover Maven, Gradle, compiler --release, build tooling, source launch, and runtime images.\n",
        encoding="utf-8",
    )
    openjdk_source = tmp_path / "openjdk.md"
    openjdk_source.write_text(
        "# OpenJDK Java 25\n\n"
        "- OpenJDK Java 25 JEP facts include language features, API changes, removals, deprecations, build tooling, and runtime performance changes.\n"
        "- OpenJDK Java 25 documents Unsafe deprecation, JNI integrity restrictions, security manager impact, crypto updates, and security-native concerns.\n",
        encoding="utf-8",
    )
    migration_preparing_source = tmp_path / "java-migration-preparing.md"
    migration_preparing_source.write_text(
        "# Java 25 Preparing for Migration\n\n"
        "- Migration from Java 21 to Java 25 requires compatibility checks, compiler warning review, dependency validation, and source upgrade planning.\n"
        "- Migration guidance must cover Maven and Gradle build tooling, compiler --release settings, runtime behavior, and security-native risks.\n",
        encoding="utf-8",
    )
    removed_apis_source = tmp_path / "java-removed-apis.md"
    removed_apis_source.write_text(
        "# Java 25 Removed APIs\n\n"
        "- Java 25 migration requires review of removed APIs, deprecated APIs, deprecation warnings, and breaking compatibility changes before compiling migrated code.\n",
        encoding="utf-8",
    )
    removed_tools_source = tmp_path / "java-removed-tools.md"
    removed_tools_source.write_text(
        "# Java 25 Removed Tools\n\n"
        "- Java 25 migration requires checking removed tools, removed components, build tooling scripts, runtime image generation, and deployment automation.\n",
        encoding="utf-8",
    )
    return {
        "openjdk-jdk-25-project": openjdk_source,
        "oracle-java-25-api": api_source,
        "oracle-java-25-release-notes": release_source,
        "oracle-java-25-migration-preparing": migration_preparing_source,
        "oracle-java-25-removed-apis": removed_apis_source,
        "oracle-java-25-removed-tools": removed_tools_source,
    }


def _assert_pending_review_pack(result) -> None:
    assert result.request.is_ready is True
    assert result.pack is not None
    assert result.pack_version is not None
    assert result.pack.key == "java-21-to-25"
    assert result.pack_version.status == "pending_review"
    assert result.pack_version.quality_status == "passed"
    assert result.pack_version.compatibility_facts["target_version_exactness"] == {"java": True}
    assert result.pack_version.compatibility_facts["archived_source_keys"] == [
        "openjdk-jdk-25-project",
        "oracle-java-25-api",
        "oracle-java-25-migration-preparing",
        "oracle-java-25-release-notes",
        "oracle-java-25-removed-apis",
        "oracle-java-25-removed-tools",
    ]
    assert result.build_run.status == "pending_review"
    assert result.build_run.publish_decision == "requires_approval"
    assert result.build_run.approval_status == "pending"
    assert result.quality_report["archived_source_count"] == 6
    assert result.quality_report["retrievable_item_count"] == 6
    assert result.quality_report["item_evidence_complete_count"] == 6
    assert result.quality_report["item_evidence_fact_complete_count"] == 6
    assert result.quality_report["item_metadata_complete_count"] == 6
    assert result.quality_report["evidence_fact_count"] >= 4
    assert result.quality_report["coverage_matrix_passed"] is True
    assert result.quality_report["coding_agent_evaluation_status"] == "passed"
    assert result.quality_report["adversarial_review_status"] == "passed"
    assert result.quality_report["passed"] is True


async def _assert_archived_sources_and_items(db, result) -> None:
    sources = (
        await db.execute(
            select(EngineeringKnowledgePackSource)
            .where(EngineeringKnowledgePackSource.pack_version_id == result.pack_version.id)
            .order_by(EngineeringKnowledgePackSource.source_key.asc())
        )
    ).scalars().all()
    assert [source.fetch_status for source in sources] == [
        "fetched",
        "fetched",
        "fetched",
        "fetched",
        "fetched",
        "fetched",
    ]
    assert all(source.checksum for source in sources)
    assert all(source.raw_archive_path for source in sources)
    assert all(source.parsed_archive_path for source in sources)
    assert all(source.source_metadata.get("original_source_uri") for source in sources)

    items = (
        await db.execute(select(EngineeringKnowledgePackItem).where(EngineeringKnowledgePackItem.pack_version_id == result.pack_version.id))
    ).scalars().all()
    assert len(items) == 6
    assert all(item.content for item in items)
    assert all(item.item_metadata["generated_by"] == "engineering_pack_research_agent" for item in items)
    assert all(item.item_metadata["evidence"][0]["source_key"] for item in items)
    assert all(item.item_metadata["evidence_fact_ids"] for item in items)


@pytest.mark.asyncio
async def test_build_engineering_pack_draft_with_archived_fixture_sources(db, tmp_path):
    source_overrides = _write_java_25_fixture_sources(tmp_path)

    result = await build_engineering_knowledge_pack_draft(
        db,
        request=pack_build_request_from_fields(
            {"source_versions": {"java": "21"}, "target_versions": {"java": "25"}},
            publish_policy={"auto_publish": True, "approval_required": False},
        ),
        trigger="agent_tool",
        archive_base_path=tmp_path / "archive",
        source_overrides=source_overrides,
        allowed_roots=[tmp_path],
    )
    await db.commit()

    _assert_pending_review_pack(result)

    await _assert_archived_sources_and_items(db, result)
