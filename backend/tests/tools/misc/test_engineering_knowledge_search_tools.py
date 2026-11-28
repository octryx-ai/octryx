"""Engineering pack read tools: registration, bounded search, get and resolve, retrieval of active facts and sources, review drafts in search-all, and target aliases resolving to the latest draft."""

from __future__ import annotations

import pytest

from app.services.engineering_knowledge.retrieval_index import rebuild_engineering_knowledge_retrieval_index
from app.tools.registry import TOOL_REGISTRY, execute_tool, get_tool_definitions
from tests.tools.misc.engineering_knowledge_search_tools_support import _context, _create_published_java_pack


def test_engineering_pack_read_tools_are_registered():
    names = {definition["function"]["name"] for definition in get_tool_definitions(agent_type="diagnosis")}

    assert "engineering_pack_search" in TOOL_REGISTRY
    assert "engineering_pack_retrieve" in TOOL_REGISTRY
    assert "engineering_pack_get" in TOOL_REGISTRY
    assert "engineering_pack_resolve_for_task" in TOOL_REGISTRY
    assert "engineering_pack_search" in names
    assert "engineering_pack_retrieve" in names
    assert "engineering_pack_get" in names
    assert "engineering_pack_resolve_for_task" in names


@pytest.mark.asyncio
async def test_engineering_pack_search_get_and_resolve_tools_return_bounded_context(db, tmp_path):
    version = await _create_published_java_pack(db)
    context = _context(db, tmp_path)

    search = await execute_tool(
        "engineering_pack_search",
        {
            "stack_key": "java-spring",
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
            "topic": "dependency-management",
        },
        context,
    )

    assert search["status"] == "ok"
    assert search["count"] == 1
    assert search["packs"][0]["pack_version_id"] == version.id
    assert search["packs"][0]["matching_items"][0]["source_key"] == "spring-boot-4-0-3-reference"

    detail = await execute_tool("engineering_pack_get", {"pack_version_id": version.id, "max_items": 1}, context)

    assert detail["status"] == "ok"
    assert detail["pack"]["status"] == "published"
    assert detail["pack"]["quality_status"] == "passed"
    assert detail["pack"]["sources"][0]["trust_tier"] == "official"
    assert detail["pack"]["items"][0]["metadata"]["evidence"][0]["source_key"] == "spring-boot-4-0-3-reference"

    resolved = await execute_tool(
        "engineering_pack_resolve_for_task",
        {
            "stack_key": "java-spring",
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
            "max_items": 1,
        },
        context,
    )

    assert resolved["status"] == "ok"
    assert resolved["pack"]["pack_version_id"] == version.id
    assert resolved["pack"]["items"][0]["title"] == "Spring Boot 4 runtime baseline"


@pytest.mark.asyncio
async def test_engineering_pack_retrieve_searches_active_fact_and_source_records(db, tmp_path):
    version = await _create_published_java_pack(db)
    context = _context(db, tmp_path)

    fact_search = await execute_tool(
        "engineering_pack_retrieve",
        {
            "stack_key": "java-spring",
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
            "record_kind": "fact",
            "query": "Java 25 BOM evidence",
            "coverage_area": "build_tooling",
        },
        context,
    )

    assert fact_search["status"] == "ok"
    assert fact_search["count"] == 1
    assert fact_search["records"][0]["record_kind"] == "fact"
    assert fact_search["records"][0]["fact_id"] == "spring-boot-4-java-25-fact"
    assert fact_search["records"][0]["source_key"] == "spring-boot-4-0-3-reference"
    assert fact_search["records"][0]["archive_path"] == "engineering-knowledge/test/evidence.json"

    source_search = await execute_tool(
        "engineering_pack_retrieve",
        {
            "stack_key": "java-spring",
            "record_kind": "source",
            "query": "Spring Boot 4.0.3 Reference",
            "trust_tier": "official",
        },
        context,
    )

    assert source_search["status"] == "ok"
    assert source_search["count"] == 1
    assert source_search["records"][0]["record_kind"] == "source"
    assert source_search["records"][0]["canonical_uri"] == "https://docs.spring.io/spring-boot/4.0.3/reference/index.html"

    version.status = "draft"
    await rebuild_engineering_knowledge_retrieval_index(db, pack_version_id=version.id)
    await db.commit()

    hidden = await execute_tool(
        "engineering_pack_retrieve",
        {"stack_key": "java-spring", "query": "BOM evidence", "record_kind": "fact"},
        context,
    )

    assert hidden["status"] == "ok"
    assert hidden["count"] == 0


@pytest.mark.asyncio
async def test_engineering_pack_search_all_includes_review_drafts_with_item_trust_tier(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    version.items[0].item_metadata = {"trust_tier": "official"}
    await db.commit()

    search = await execute_tool(
        "engineering_pack_search",
        {
            "stack_key": "java-spring",
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
            "topic": "dependency-management",
            "status": "all",
            "quality_status": "all",
            "trust_tier": "official",
        },
        _context(db, tmp_path),
    )

    assert search["status"] == "ok"
    assert search["count"] == 1
    assert search["packs"][0]["pack_version_id"] == version.id


@pytest.mark.asyncio
async def test_engineering_pack_get_resolves_target_alias_to_latest_draft(db, tmp_path):
    version = await _create_published_java_pack(db)
    version.status = "draft"
    version.quality_status = "pending"
    await db.commit()

    detail = await execute_tool(
        "engineering_pack_get",
        {"pack_key": "java-25", "max_items": 1},
        _context(db, tmp_path),
    )

    assert detail["status"] == "ok"
    assert detail["pack"]["pack_version_id"] == version.id
    assert detail["pack"]["pack_key"] == "java-21-to-25-spring-boot-3.4-to-4.0.3"
