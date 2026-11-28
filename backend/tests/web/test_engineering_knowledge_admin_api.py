from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
    EngineeringKnowledgeRetrievalIndex,
)
from app.web.routers import panel_engineering_knowledge as engineering_knowledge_router
from tests.conftest import ADMIN_PASSWORD


async def _login_admin(client) -> None:
    resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 303


async def _create_quality_passed_pack(db) -> tuple[EngineeringKnowledgePack, EngineeringKnowledgePackVersion]:
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key=f"java-21-to-25-spring-boot-34-to-403-{uuid.uuid4().hex[:8]}",
        name="Java 21 to 25 / Spring Boot 3.4 to 4.0.3 Engineering Knowledge Pack",
        description="Fixture pack for admin review flow.",
        stack_key="java-spring",
        lifecycle_status="active",
        source_policy={"trust_tiers": ["official"]},
        freshness_policy={"ttl_days": 30},
        retrieval_policy={"default_context_budget_tokens": 12000},
        resolution_policy={"ask_user_on_ambiguity": True},
        is_active=True,
    )
    version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack_id=pack.id,
        version=1,
        status="pending_review",
        source_versions={"java": "21", "spring_boot": "3.4"},
        target_versions={"java": "25", "spring_boot": "4.0.3"},
        compatibility_facts={"stack_key": "java-spring"},
        manifest={
            "schema_version": 1,
            "sources": [],
            "evidence_ledger": [
                {
                    "fact_id": "java-25-fact-1",
                    "claim": "JEP 503 removes the 32-bit x86 port in JDK 25.",
                    "coverage_areas": ["features", "removals_deprecations"],
                    "source_key": "openjdk-jdk-25-project",
                    "source_uri": "https://openjdk.org/projects/jdk/25/",
                    "archive_path": "engineering-knowledge/test/v1/source.parsed.txt",
                    "usable_for_pack": True,
                }
            ],
        },
        archive_root="engineering-knowledge/test/v1",
        quality_status="passed",
        quality_report={"passed": True, "blockers": []},
    )
    source = EngineeringKnowledgePackSource(
        id=str(uuid.uuid4()),
        pack_version_id=version.id,
        source_key="openjdk-jdk-25-project",
        title="OpenJDK JDK 25",
        source_uri="https://openjdk.org/projects/jdk/25/",
        source_type="release_notes",
        trust_tier="official",
        version_label="25",
        checksum="abc123",
        fetch_status="fetched",
        freshness_status="fresh",
        raw_archive_path="engineering-knowledge/test/v1/source.raw.txt",
        parsed_archive_path="engineering-knowledge/test/v1/source.parsed.txt",
        evidence_archive_path="engineering-knowledge/test/v1/evidence.json",
        source_metadata={
            "source_audit": {
                "status": "accepted",
                "canonical_uri": "https://openjdk.org/projects/jdk/25/",
                "coverage_areas": ["release_notes"],
            }
        },
    )
    item = EngineeringKnowledgePackItem(
        id=str(uuid.uuid4()),
        pack_version_id=version.id,
        source_id=source.id,
        item_key="java-25-migration-guidance",
        title="Java 25 migration guidance",
        summary="Use source-backed Java 25 migration guidance.",
        content="Use this Java 25 evidence before changing migration code.",
        tags=["java", "migration"],
        triggers=["java", "25", "migration"],
        version_scope={"target_versions": {"java": "25"}},
        retrieval_priority="high",
        retrieval_rank=10,
        item_metadata={"evidence_fact_ids": ["java-25-fact-1"]},
    )
    db.add_all([pack, version, source, item])
    await db.commit()
    return pack, version


@pytest.mark.asyncio
async def test_engineering_knowledge_admin_api_builds_reviewable_metadata_only_run(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(engineering_knowledge_router, "WORKSPACE_ROOT", tmp_path)
    await _login_admin(client)

    resp = await client.post(
        "/admin/chat/api/panel/engineering-knowledge/build-runs",
        json={
            "source_versions": {"java": "21", "spring_boot": "3.4"},
            "target_versions": {"java": "25", "spring_boot": "4.0.3"},
            "allow_network": False,
        },
    )

    assert resp.status_code == 200, resp.text
    run = resp.json()
    assert run["status"] == "blocked"
    assert run["stack_key"] == "java-spring"
    assert run["source_versions"] == {"java": "21", "spring_boot": "3.4"}
    assert run["target_versions"] == {"java": "25", "spring_boot": "4.0.3"}
    assert run["pack_id"]
    assert run["pack_version_id"]
    assert run["source_plan"]["requires_online_acquisition"] is True
    blocker_codes = {item["code"] for item in run["blocker_details"]}
    assert "insufficient_archived_sources" in blocker_codes
    assert "source_audit_not_passed" in blocker_codes

    detail_resp = await client.get(f"/admin/chat/api/panel/engineering-knowledge/packs/{run['pack_id']}")
    assert detail_resp.status_code == 200, detail_resp.text
    pack = detail_resp.json()
    version = pack["versions"][0]
    assert version["quality_status"] == "failed"
    assert version["source_count"] == 9
    assert {source["fetch_status"] for source in version["sources"]} == {"metadata_only"}
    assert all(source["evidence_archive_path"] for source in version["sources"])

    list_resp = await client.get("/admin/chat/api/panel/engineering-knowledge/build-runs")
    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json()["build_runs"][0]["id"] == run["id"]


@pytest.mark.asyncio
async def test_engineering_knowledge_admin_api_publishes_and_assigns_quality_passed_version(admin_client, db):
    pack, version = await _create_quality_passed_pack(db)

    publish_resp = await admin_client.post(
        f"/admin/chat/api/panel/engineering-knowledge/versions/{version.id}/publish",
    )
    assert publish_resp.status_code == 200, publish_resp.text
    published = publish_resp.json()
    assert published["status"] == "published"
    assert published["published_by_user_id"]
    assert published["quality_report"]["retrieval_index"]["indexed_record_count"] == 4
    index_records = (
        await db.execute(
            select(EngineeringKnowledgeRetrievalIndex).where(
                EngineeringKnowledgeRetrievalIndex.pack_version_id == version.id,
                EngineeringKnowledgeRetrievalIndex.is_active.is_(True),
            )
        )
    ).scalars().all()
    assert {record.record_kind for record in index_records} == {"pack", "source", "item", "fact"}
    search_resp = await admin_client.get(
        f"/admin/chat/api/panel/engineering-knowledge/versions/{version.id}/retrieval-index",
        params={"query": "JEP 503", "record_kind": "fact"},
    )
    assert search_resp.status_code == 200, search_resp.text
    search = search_resp.json()
    assert search["count"] == 1
    assert search["records"][0]["record_kind"] == "fact"
    assert search["records"][0]["fact_id"] == "java-25-fact-1"
    assert search["records"][0]["canonical_uri"] == "https://openjdk.org/projects/jdk/25/"

    assign_resp = await admin_client.post(
        f"/admin/chat/api/panel/engineering-knowledge/versions/{version.id}/assignments",
        json={
            "scope_type": "global",
            "assignment_policy": {"resolution": "automatic", "manual_user_selection": False},
        },
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assignment = assign_resp.json()
    assert assignment["assignment_status"] == "active"
    assert assignment["scope_type"] == "global"
    assert assignment["stack_key"] == "java-spring"
    assert assignment["assignment_policy"]["manual_user_selection"] is False

    detail_resp = await admin_client.get(f"/admin/chat/api/panel/engineering-knowledge/packs/{pack.id}")
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["latest_published_version_id"] == version.id
    assert detail["versions"][0]["active_assignment_count"] == 1


@pytest.mark.asyncio
async def test_engineering_knowledge_admin_api_blocks_failed_publish_and_allows_rejection(
    client,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(engineering_knowledge_router, "WORKSPACE_ROOT", tmp_path)
    await _login_admin(client)
    create_resp = await client.post(
        "/admin/chat/api/panel/engineering-knowledge/build-runs",
        json={
            "source_versions": {"java": "21"},
            "target_versions": {"java": "25"},
            "allow_network": False,
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    version_id = create_resp.json()["pack_version_id"]

    publish_resp = await client.post(
        f"/admin/chat/api/panel/engineering-knowledge/versions/{version_id}/publish",
    )
    assert publish_resp.status_code == 400
    assert "quality-passed" in publish_resp.text

    reject_resp = await client.post(
        f"/admin/chat/api/panel/engineering-knowledge/versions/{version_id}/reject",
        json={"reason": "Evidence was not archived yet."},
    )
    assert reject_resp.status_code == 200, reject_resp.text
    rejected = reject_resp.json()
    assert rejected["status"] == "rejected"
    assert rejected["quality_report"]["admin_review"]["reason"] == "Evidence was not archived yet."
