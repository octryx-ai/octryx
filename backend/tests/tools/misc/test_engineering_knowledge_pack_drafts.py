"""Engineering pack draft tools: reusing an editable draft, adding reviewable source evidence with its audit, and the requirements to finalize."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import EngineeringKnowledgePackItem, EngineeringKnowledgePackSource
from app.tools.registry import execute_tool
from tests.tools.misc.engineering_knowledge_search_tools_support import _context, _create_published_java_pack


@pytest.mark.asyncio
async def test_pack_draft_create_reuses_matching_editable_draft(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    await db.commit()

    result = await execute_tool(
        "pack_draft_create",
        {
            "pack_name": "Java Spring migration pack",
            "stack_key": "java-spring",
            "source_versions": {"java": "21", "spring_boot": "3.4"},
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
        },
        _context(db, tmp_path),
    )

    assert result["reused_existing_draft"] is True
    assert result["pack_version_id"] == version.id
    assert result["item_count"] == 1


@pytest.mark.asyncio
async def test_pack_draft_add_item_rejects_placeholder_content(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    await db.commit()

    result = await execute_tool(
        "pack_draft_add_item",
        {
            "pack_version_id": version.id,
            "item_key": "placeholder",
            "title": "Placeholder",
            "content": "TODO",
        },
        _context(db, tmp_path),
    )

    assert result["error"] == "content must be substantive; placeholder values like TODO are not allowed"


@pytest.mark.asyncio
async def test_pack_draft_add_item_creates_reviewable_source_evidence(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    await db.commit()

    result = await execute_tool(
        "pack_draft_add_item",
        {
            "pack_version_id": version.id,
            "item_key": "java25-reviewable-evidence",
            "title": "Java 25 reviewable evidence",
            "content": (
                "Java 25 migration guidance must be backed by official source evidence. "
                "This item intentionally contains enough source-backed guidance to pass the minimum content gate."
            ),
            "source_uri": "context7://java/migration",
            "trust_tier": "official",
        },
        _context(db, tmp_path),
    )

    assert result["updated"] is False
    await db.commit()

    created_item = (
        await db.execute(
            select(EngineeringKnowledgePackItem).where(
                EngineeringKnowledgePackItem.pack_version_id == version.id,
                EngineeringKnowledgePackItem.item_key == "java25-reviewable-evidence",
            )
        )
    ).scalar_one()

    assert created_item.source_id is not None
    assert created_item.item_metadata["source_uri"] == "context7://java/migration"
    assert created_item.item_metadata["evidence"][0]["source_uri"] == "context7://java/migration"
    source = await db.get(EngineeringKnowledgePackSource, created_item.source_id)
    assert source is not None
    assert source.raw_archive_path
    assert source.parsed_archive_path
    assert source.evidence_archive_path
    assert source.source_metadata["source_audit"]["status"] == "rejected"
    assert "context7_snippets_are_source_candidates_only" in source.source_metadata["source_audit"]["blockers"]


@pytest.mark.asyncio
async def test_pack_draft_add_item_records_accepted_source_audit_for_canonical_url(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    await db.commit()

    result = await execute_tool(
        "pack_draft_add_item",
        {
            "pack_version_id": version.id,
            "item_key": "java25-official-source-audit",
            "title": "Java 25 official source audit",
            "content": (
                "Java 25 migration guidance must be backed by canonical official source evidence. "
                "This item intentionally contains enough source-backed guidance to exercise source audit metadata."
            ),
            "source_uri": "https://openjdk.org/projects/jdk/25/jeps-since-jdk-21",
            "trust_tier": "official",
        },
        _context(db, tmp_path),
    )

    assert result["updated"] is False
    await db.commit()

    source = (
        await db.execute(
            select(EngineeringKnowledgePackSource).where(
                EngineeringKnowledgePackSource.pack_version_id == version.id,
                EngineeringKnowledgePackSource.source_key.like("java25-official-source-audit-%"),
            )
        )
    ).scalar_one()

    assert source.source_metadata["source_audit"]["status"] == "accepted"
    assert source.source_metadata["source_audit"]["canonical_uri"] == "https://openjdk.org/projects/jdk/25/jeps-since-jdk-21"


@pytest.mark.asyncio
async def test_pack_draft_finalize_requires_minimum_reviewable_items(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    await db.commit()

    await execute_tool(
        "pack_draft_add_item",
        {
            "pack_version_id": version.id,
            "item_key": "java25-official-evidence",
            "title": "Java 25 official evidence",
            "content": (
                "Java 25 migration guidance must be backed by official source evidence. "
                "This item intentionally contains enough source-backed guidance to pass the minimum content gate."
            ),
            "source_uri": "https://openjdk.org/projects/jdk/25/jeps-since-jdk-21",
            "trust_tier": "official",
        },
        _context(db, tmp_path),
    )
    await db.commit()

    result = await execute_tool(
        "pack_draft_finalize",
        {"pack_key": "java-25"},
        _context(db, tmp_path),
    )

    assert result["quality_status"] == "blocked"
    assert result["item_count"] == 2
    assert any("at least 5 reviewable items" in blocker for blocker in result["blockers"])


@pytest.mark.asyncio
async def test_pack_draft_finalize_requires_archived_canonical_sources(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    await db.commit()

    await execute_tool(
        "pack_draft_add_item",
        {
            "pack_version_id": version.id,
            "item_key": "java25-context7-only",
            "title": "Java 25 context7 only",
            "content": (
                "Java 25 migration guidance must be backed by official source evidence. "
                "This content is archived locally, but its source URI intentionally remains a tool-internal URI."
            ),
            "source_uri": "context7://java/migration",
            "trust_tier": "official",
        },
        _context(db, tmp_path),
    )
    await db.commit()

    result = await execute_tool(
        "pack_draft_finalize",
        {"pack_version_id": version.id},
        _context(db, tmp_path),
    )

    assert result["quality_status"] == "blocked"
    assert any("canonical HTTP(S)" in blocker for blocker in result["blockers"])
