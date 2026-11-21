"""Ingesting local and URL sources archives raw and parsed evidence with a manifest, replaces stable source keys, and enforces allowed roots, offline metadata-only registration and download limits."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.models import EngineeringKnowledgePack, EngineeringKnowledgePackItem, EngineeringKnowledgePackVersion
from app.services.engineering_knowledge import (
    EngineeringKnowledgeSourceSpec,
    export_engineering_knowledge_manifest,
    ingest_engineering_knowledge_source,
)


async def _create_pack_version(db, *, key: str = "java-spring-21-to-25"):
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key=key,
        name="Java Spring Migration",
        stack_key="java-spring",
        freshness_policy={"ttl_days": 30, "warning_days": 21},
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack=pack,
        version=1,
        status="draft",
        source_versions={"java": "21", "spring_boot": "3.4.x"},
        target_versions={"java": "25", "spring_boot": "4.0.3"},
    )
    db.add_all([pack, version])
    await db.flush()
    return pack, version


@pytest.mark.asyncio
async def test_ingest_local_source_archives_raw_parsed_evidence_and_manifest(db, tmp_path):
    pack, version = await _create_pack_version(db)
    source_file = tmp_path / "java25-notes.md"
    source_file.write_text("# Java 25\n\nUse exact Java 25 documentation for migration facts.\n", encoding="utf-8")

    source = await ingest_engineering_knowledge_source(
        db,
        pack_version=version,
        pack_slug=pack.key,
        source_spec=EngineeringKnowledgeSourceSpec(
            source_key="oracle-java-25-release-notes",
            title="Java 25 Release Notes",
            source_uri=str(source_file),
            source_type="release_notes",
            trust_tier="official",
            version_label="25",
            metadata={"coordinate": "java", "target_version": "25"},
        ),
        archive_base_path=tmp_path / "archive",
        allowed_roots=[tmp_path],
        freshness_policy=pack.freshness_policy,
    )
    db.add(
        EngineeringKnowledgePackItem(
            id=str(uuid.uuid4()),
            pack_version_id=version.id,
            source_id=source.id,
            item_key="java-25-release-note-item",
            title="Java 25 migration evidence",
            summary="Use exact Java 25 documentation.",
            content="Use exact Java 25 documentation for migration facts.",
            tags=["java-spring", "migration"],
            version_scope={"target_versions": version.target_versions},
            retrieval_rank=10,
        )
    )
    await db.commit()

    archive_base = tmp_path / "archive"
    assert source.fetch_status == "fetched"
    assert source.freshness_status == "fresh"
    assert source.checksum
    assert source.raw_archive_path and (archive_base / source.raw_archive_path).is_file()
    assert source.parsed_archive_path and (archive_base / source.parsed_archive_path).is_file()
    assert source.evidence_archive_path and (archive_base / source.evidence_archive_path).is_file()
    assert "Java 25" in (archive_base / source.parsed_archive_path).read_text(encoding="utf-8")

    evidence = json.loads((archive_base / source.evidence_archive_path).read_text(encoding="utf-8"))
    assert evidence["checksum"] == source.checksum
    assert evidence["fetch_status"] == "fetched"
    assert evidence["fetched_at"]

    manifest = await export_engineering_knowledge_manifest(db, pack_version=version)
    assert manifest["schema_version"] == 2
    assert manifest["manifest_kind"] == "engineering_knowledge_pack"
    assert manifest["pack"]["key"] == pack.key
    assert manifest["pack"]["stack_key"] == "java-spring"
    assert manifest["items"][0]["source_key"] == "oracle-java-25-release-notes"
    assert manifest["export"]["contains_archive_paths"] is True
    assert manifest["export"]["export_ready"] is False
    assert manifest["quality_inputs"]["official_source_count"] == 1
    assert manifest["quality_inputs"]["target_version_exactness"]["java"] is True
    assert manifest["quality_inputs"]["target_version_exactness"]["spring_boot"] is False


@pytest.mark.asyncio
async def test_ingest_url_source_uses_response_content_type_for_suffix_and_parser(db, tmp_path, monkeypatch):
    pack, version = await _create_pack_version(db)
    source_uri = "https://docs.openrewrite.org/recipes/java/spring/boot4"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<html><body><h1>OpenRewrite Boot 4</h1><p>Migration recipes</p></body></html>",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(
        "app.services.engineering_knowledge.source_ingestion_archive.httpx.AsyncClient",
        FakeAsyncClient,
    )

    source = await ingest_engineering_knowledge_source(
        db,
        pack_version=version,
        pack_slug=pack.key,
        source_spec=EngineeringKnowledgeSourceSpec(
            source_key="openrewrite-spring-boot-4-0-3-recipes",
            title="OpenRewrite Spring Boot 4 Migration Recipes",
            source_uri=source_uri,
            source_type="recipe_catalog",
            trust_tier="vendor",
            version_label="4.0.3",
            metadata={"coordinate": "spring_boot", "target_version": "4.0.3"},
        ),
        archive_base_path=tmp_path / "archive",
        allow_network=True,
    )

    archive_base = tmp_path / "archive"
    assert source.fetch_status == "fetched"
    assert source.raw_archive_path and source.raw_archive_path.endswith(".html")
    assert source.parsed_archive_path
    assert "OpenRewrite Boot 4" in (archive_base / source.parsed_archive_path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_ingest_replaces_existing_source_for_stable_source_keys(db, tmp_path):
    pack, version = await _create_pack_version(db)
    source_file = tmp_path / "spring-boot.md"
    source_file.write_text("first version", encoding="utf-8")
    spec = EngineeringKnowledgeSourceSpec(
        source_key="spring-boot-4-0-3-reference",
        title="Spring Boot 4.0.3 Reference",
        source_uri=str(source_file),
        source_type="documentation",
        trust_tier="official",
        version_label="4.0.3",
        metadata={"coordinate": "spring_boot", "target_version": "4.0.3"},
    )

    first = await ingest_engineering_knowledge_source(
        db,
        pack_version=version,
        pack_slug=pack.key,
        source_spec=spec,
        archive_base_path=tmp_path / "archive",
        allowed_roots=[tmp_path],
    )
    first_id = first.id
    first_checksum = first.checksum
    source_file.write_text("second version", encoding="utf-8")

    second = await ingest_engineering_knowledge_source(
        db,
        pack_version=version,
        pack_slug=pack.key,
        source_spec=spec,
        archive_base_path=tmp_path / "archive",
        allowed_roots=[tmp_path],
    )

    assert second.id == first_id
    assert second.checksum != first_checksum


@pytest.mark.asyncio
async def test_url_source_without_network_registers_metadata_only(db, tmp_path):
    pack, version = await _create_pack_version(db)

    source = await ingest_engineering_knowledge_source(
        db,
        pack_version=version,
        pack_slug=pack.key,
        source_spec={
            "source_key": "spring-boot-4-0-3-dependencies",
            "title": "Spring Boot 4.0.3 Dependency Versions",
            "source_uri": "https://docs.spring.io/spring-boot/4.0.3/appendix/dependency-versions/index.html",
            "source_type": "bom",
            "trust_tier": "official",
            "version_label": "4.0.3",
            "metadata": {"coordinate": "spring_boot", "target_version": "4.0.3"},
        },
        archive_base_path=tmp_path / "archive",
        allow_network=False,
    )

    assert source.fetch_status == "metadata_only"
    assert source.freshness_status == "unknown"
    assert source.checksum is None
    assert source.raw_archive_path is None
    assert source.parsed_archive_path is None
    assert source.evidence_archive_path
    evidence = json.loads(((tmp_path / "archive") / source.evidence_archive_path).read_text(encoding="utf-8"))
    assert evidence["final_uri"] == source.source_uri


@pytest.mark.asyncio
async def test_ingest_rejects_local_sources_outside_allowed_roots(db, tmp_path):
    pack, version = await _create_pack_version(db)
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}.md"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ValueError, match="allowed root"):
        await ingest_engineering_knowledge_source(
            db,
            pack_version=version,
            pack_slug=pack.key,
            source_spec=EngineeringKnowledgeSourceSpec(
                source_key="outside-source",
                title="Outside Source",
                source_uri=str(outside),
            ),
            archive_base_path=tmp_path / "archive",
            allowed_roots=[tmp_path],
        )


@pytest.mark.asyncio
async def test_ingest_enforces_max_download_bytes_for_local_sources(db, tmp_path):
    pack, version = await _create_pack_version(db)
    source_file = tmp_path / "large.md"
    source_file.write_text("too large", encoding="utf-8")

    with pytest.raises(ValueError, match="max_download_bytes"):
        await ingest_engineering_knowledge_source(
            db,
            pack_version=version,
            pack_slug=pack.key,
            source_spec=EngineeringKnowledgeSourceSpec(
                source_key="large-source",
                title="Large Source",
                source_uri=str(source_file),
            ),
            archive_base_path=tmp_path / "archive",
            allowed_roots=[tmp_path],
            max_download_bytes=3,
        )
