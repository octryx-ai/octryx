"""Pack building blocks without archived evidence, records a blocker run for a target-only request, and the quality gate blocks disallowed tiers and items without evidence."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import (
    EngineeringKnowledgePackBuildRun,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)
from app.services.engineering_knowledge import build_engineering_knowledge_pack_draft, pack_build_request_from_fields
from app.services.engineering_knowledge.pack_builder_quality import _evaluate_manifest_quality


@pytest.mark.asyncio
async def test_build_engineering_pack_blocks_without_archived_evidence(db, tmp_path):
    result = await build_engineering_knowledge_pack_draft(
        db,
        request=pack_build_request_from_fields(
            {"source_versions": {"java": "21"}, "target_versions": {"java": "25"}}
        ),
        trigger="agent_tool",
        archive_base_path=tmp_path / "archive",
        allow_network=False,
    )

    assert result.pack is not None
    assert result.pack_version is not None
    assert result.build_run.status == "blocked"
    assert result.build_run.publish_decision == "blocked"
    assert result.pack_version.status == "draft"
    assert result.pack_version.quality_status == "failed"
    assert result.blockers[0]["code"] == "insufficient_archived_sources"

    sources = (
        await db.execute(
            select(EngineeringKnowledgePackSource).where(
                EngineeringKnowledgePackSource.pack_version_id == result.pack_version.id
            )
        )
    ).scalars().all()
    assert [source.fetch_status for source in sources] == [
        "metadata_only",
        "metadata_only",
        "metadata_only",
        "metadata_only",
        "metadata_only",
        "metadata_only",
    ]
    assert all(source.checksum is None for source in sources)


@pytest.mark.asyncio
async def test_build_engineering_pack_records_blocker_run_for_target_only_request(db, tmp_path):
    existing_versions = (await db.execute(select(EngineeringKnowledgePackVersion))).scalars().all()
    result = await build_engineering_knowledge_pack_draft(
        db,
        request=pack_build_request_from_fields({"target_versions": {"java": "25"}}),
        trigger="agent_tool",
        archive_base_path=tmp_path / "archive",
    )
    await db.commit()

    runs = (await db.execute(select(EngineeringKnowledgePackBuildRun))).scalars().all()
    versions = (await db.execute(select(EngineeringKnowledgePackVersion))).scalars().all()
    assert result.pack is None
    assert result.pack_version is None
    assert result.build_run.status == "blocked"
    assert result.build_run.blocker_details[0]["code"] == "missing_source_versions"
    assert len(runs) == 1
    assert len(versions) == len(existing_versions)


def test_engineering_pack_quality_blocks_disallowed_tiers_and_missing_item_evidence():
    report = _evaluate_manifest_quality(
        {
            "sources": [
                {
                    "source_key": "community-blog",
                    "trust_tier": "community",
                    "fetch_status": "fetched",
                    "freshness_status": "fresh",
                    "checksum": "abc123",
                }
            ],
            "items": [
                {
                    "item_key": "migration-note",
                    "source_key": None,
                    "title": "Migration note",
                    "summary": "",
                    "metadata": {},
                }
            ],
            "quality_inputs": {
                "target_version_exactness": {"java": True},
                "item_count": 1,
                "item_evidence_complete_count": 0,
                "item_metadata_complete_count": 0,
            },
        },
        source_plan={"sources": [{"source_key": "community-blog"}]},
        source_policy={"trust_tiers": ["official"], "min_archived_sources": 1},
    )

    assert report["passed"] is False
    assert {blocker["code"] for blocker in report["blockers"]} == {
        "disallowed_source_trust_tier",
        "source_audit_not_passed",
        "missing_item_evidence",
        "missing_evidence_ledger",
        "missing_item_evidence_facts",
        "coverage_matrix_not_passed",
        "coding_agent_evaluation_failed",
        "adversarial_review_failed",
        "incomplete_retrievable_items",
    }
