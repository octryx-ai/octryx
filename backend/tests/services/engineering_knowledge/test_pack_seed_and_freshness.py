"""Research follow-ups: seeding pack drafts from research evidence (with
deterministic trust-tier inference) and freshness staleness detection."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models.project.engineering_knowledge import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackVersion,
)
from app.services.engineering_knowledge.pack_seed import (
    infer_trust_tier,
    list_stale_engineering_knowledge_packs,
    seed_pack_sources,
)
from app.time_utils import utc_now


def test_trust_tier_inference_is_deterministic():
    assert infer_trust_tier("https://spring.io/blog/2025/11/20/spring-boot-4-0") == "official"
    assert infer_trust_tier("https://docs.spring.io/spring-boot/4.0/reference/") == "official"
    assert infer_trust_tier("https://github.com/spring-projects/spring-boot/wiki") == "vendor"
    assert infer_trust_tier("https://some-blog.example.com/spring-boot-4") == "community"


@pytest.mark.asyncio
async def test_seed_pack_sources_registers_and_dedupes(db):
    token = uuid.uuid4().hex[:8]
    pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()), key=f"seed-{token}", name="Seed Test", stack_key="java-spring"
    )
    version = EngineeringKnowledgePackVersion(id=str(uuid.uuid4()), pack=pack, version=1, status="draft")
    db.add_all([pack, version])
    await db.flush()

    manifest = [
        {"url": "https://spring.io/blog/spring-boot-4-0", "title": "Release blog"},
        {"url": "https://some-blog.example.com/review", "title": "Community review"},
        {"url": "https://spring.io/blog/spring-boot-4-0", "title": "duplicate"},
    ]
    registered = await seed_pack_sources(db, pack_version=version, sources=manifest)
    assert len(registered) == 2
    tiers = {entry["source_uri"]: entry["trust_tier"] for entry in registered}
    assert tiers["https://spring.io/blog/spring-boot-4-0"] == "official"
    assert tiers["https://some-blog.example.com/review"] == "community"

    # Re-seeding the same manifest registers nothing new.
    again = await seed_pack_sources(db, pack_version=version, sources=manifest)
    assert again == []


@pytest.mark.asyncio
async def test_stale_pack_detection_respects_freshness_policy(db):
    token = uuid.uuid4().hex[:8]
    fresh_pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()), key=f"fresh-{token}", name="Fresh", stack_key="java"
    )
    fresh_version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()), pack=fresh_pack, version=1, status="published", published_at=utc_now()
    )
    stale_pack = EngineeringKnowledgePack(
        id=str(uuid.uuid4()),
        key=f"stale-{token}",
        name="Stale",
        stack_key="java",
        freshness_policy={"max_age_days": 30},
    )
    stale_version = EngineeringKnowledgePackVersion(
        id=str(uuid.uuid4()),
        pack=stale_pack,
        version=1,
        status="published",
        published_at=utc_now() - timedelta(days=45),
    )
    db.add_all([fresh_pack, fresh_version, stale_pack, stale_version])
    await db.commit()

    stale = await list_stale_engineering_knowledge_packs(db)
    keys = {entry["pack_key"] for entry in stale}
    assert f"stale-{token}" in keys
    assert f"fresh-{token}" not in keys
    entry = next(item for item in stale if item["pack_key"] == f"stale-{token}")
    assert entry["age_days"] >= 45 and entry["max_age_days"] == 30
    assert "Re-research" in entry["recommendation"]
