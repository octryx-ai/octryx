from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import EngineeringKnowledgePackSource
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY, execute_tool, get_tool_definitions


def test_build_engineering_knowledge_pack_tool_is_available_to_prompt_first_runs():
    tool_names = {definition["function"]["name"] for definition in get_tool_definitions(agent_type="diagnosis")}

    assert "build_engineering_knowledge_pack" in TOOL_REGISTRY
    assert "build_engineering_knowledge_pack" in tool_names


@pytest.mark.asyncio
async def test_build_engineering_knowledge_pack_tool_creates_draft_with_fixture_sources(db, tmp_path, monkeypatch):
    archive_base = tmp_path / "engineering-archive"
    monkeypatch.setattr(
        "app.tools.knowledge_impl._engineering_knowledge_tools.default_engineering_knowledge_archive_base_path",
        lambda: archive_base,
    )
    fixture_sources = {
        "openjdk-jdk-25-project": (
            "# OpenJDK JDK 25\n\n"
            "- Java 25 JEP evidence covers language features, API changes, removals, deprecations, build tooling, runtime performance, and security-native concerns.\n"
        ),
        "oracle-java-25-api": (
            "# Java 25 API\n\n"
            "- Java 25 API evidence covers module imports, compact source files, crypto updates, key derivation, JNI integrity, and Unsafe deprecation risk.\n"
        ),
        "oracle-java-25-release-notes": (
            "# Java 25 Release Notes\n\n"
            "- Java 25 release evidence covers runtime performance, JFR profiling, AOT behavior, GC changes, Maven, Gradle, compiler --release, and runtime images.\n"
        ),
        "oracle-java-25-migration-preparing": (
            "# Java 25 Migration\n\n"
            "- Migration from Java 21 to Java 25 requires compatibility checks, source upgrades, dependency validation, build tooling review, and security-native risk review.\n"
        ),
        "oracle-java-25-removed-apis": (
            "# Java 25 Removed APIs\n\n"
            "- Java 25 removed API evidence covers removed APIs, deprecated APIs, deprecation warnings, breaking compatibility changes, and migration impact.\n"
        ),
        "oracle-java-25-removed-tools": (
            "# Java 25 Removed Tools\n\n"
            "- Java 25 removed tool evidence covers removed tools, removed components, build tooling scripts, runtime image generation, and deployment automation.\n"
        ),
    }
    source_overrides: dict[str, str] = {}
    for source_key, content in fixture_sources.items():
        path = tmp_path / f"{source_key}.md"
        path.write_text(content, encoding="utf-8")
        source_overrides[source_key] = str(path)
    context = ToolContext(
        user_id="",
        project_ids=[],
        roles=["admin"],
        session_id="session-1",
        project_config={},
        current_user_message="Erstelle ein Knowledge Pack um von Java 21 auf Java 25 zu migrieren.",
        db=db,
        workspace_root=str(tmp_path),
    )

    # The pack-build words in the user's message request nothing; only structured fields do.
    not_requested = await execute_tool(
        "build_engineering_knowledge_pack", {"source_overrides": source_overrides}, context
    )
    assert not_requested["status"] == "not_requested"
    assert not_requested["pack_id"] is None

    result = await execute_tool(
        "build_engineering_knowledge_pack",
        {
            "source_versions": {"java": "21"},
            "target_versions": {"java": "25"},
            "source_overrides": source_overrides,
            "allow_network": False,
        },
        context,
    )

    assert result["status"] == "pending_review"
    assert result["pack_key"] == "java-21-to-25"
    assert result["quality_status"] == "passed"
    assert result["publish_decision"] == "requires_approval"
    assert result["approval_status"] == "pending"
    assert result["source_plan_count"] == 6
    assert result["archived_source_count"] == 6
    assert result["archive_root"] == "engineering-knowledge/java-21-to-25/v1"
    source = (
        (
            await db.execute(
                select(EngineeringKnowledgePackSource).where(
                    EngineeringKnowledgePackSource.pack_version_id == result["pack_version_id"]
                )
            )
        )
        .scalars()
        .first()
    )
    assert source is not None
    assert (archive_base / source.raw_archive_path).is_file()
