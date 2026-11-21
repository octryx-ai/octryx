from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import EngineeringKnowledgeGraphNode, User
from app.services.engineering_knowledge import (
    cleanup_engineering_knowledge_for_deleted_source,
    expire_engineering_knowledge,
    invalidate_engineering_knowledge_by_refs,
    search_engineering_knowledge_graph,
    supersede_engineering_knowledge_node,
    upsert_engineering_knowledge_node,
)
from app.time_utils import utc_now


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def test_engineering_knowledge_expiry_marks_fact_and_excludes_retrieval(db):
    admin = await _admin(db)
    node = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="expired-java-baseline",
        display_name="Expired Java baseline",
        summary="Old Java baseline that must not be retrieved after expiry.",
        trust_level="gold",
        valid_until=utc_now() - timedelta(minutes=1),
        source_refs=[{"source_type": "policy", "source_ref": "java-baseline"}],
        created_by_user_id=admin.id,
    )
    await db.commit()

    result = await expire_engineering_knowledge(db, actor_id=admin.id)
    await db.commit()
    await db.refresh(node)

    assert result.matched_count == 1
    assert node.status == "expired"
    assert node.properties_json["lifecycle"]["source"] == "expiry_policy"
    retrieved = await search_engineering_knowledge_graph(db, query="java baseline", limit=10)
    assert node.node_key not in {item["node_key"] for item in retrieved["results"]}


async def test_engineering_knowledge_invalidation_supersession_and_cleanup(db):
    admin = await _admin(db)
    stale = await upsert_engineering_knowledge_node(
        db,
        node_type="vulnerability",
        node_key="CVE-2026-353",
        display_name="CVE-2026-353",
        summary="Initial vulnerable package guidance.",
        trust_level="gold",
        properties={"cve": "CVE-2026-353", "package": "spring-web"},
        source_refs=[{"source_type": "scanner", "source_ref": "scan-353"}],
        created_by_user_id=admin.id,
    )
    replacement = await upsert_engineering_knowledge_node(
        db,
        node_type="vulnerability",
        node_key="CVE-2026-353-v2",
        display_name="CVE-2026-353 updated",
        summary="Reviewed replacement guidance.",
        trust_level="gold",
        source_refs=[{"source_type": "scanner", "source_ref": "replacement-guidance"}],
        created_by_user_id=admin.id,
    )
    cleanup_target = await upsert_engineering_knowledge_node(
        db,
        node_type="decision",
        node_key="deleted-session-fact",
        display_name="Deleted session fact",
        summary="Fact learned from a session that was deleted.",
        trust_level="gold",
        source_refs=[{"source_type": "session", "source_ref": "session-deleted-353"}],
        created_by_user_id=admin.id,
    )
    await db.commit()

    invalidation = await invalidate_engineering_knowledge_by_refs(
        db,
        refs=["scan-353"],
        actor_id=admin.id,
        reason="Scanner finding changed upstream.",
        event_ref="event-353",
        source="test",
    )
    await supersede_engineering_knowledge_node(
        db,
        stale,
        superseded_by_node_id=replacement.id,
        actor_id=admin.id,
        reason="Reviewed replacement is available.",
    )
    cleanup = await cleanup_engineering_knowledge_for_deleted_source(
        db,
        source_refs=["session-deleted-353"],
        actor_id=admin.id,
        reason="Source session was deleted.",
    )
    await db.commit()

    refreshed = await db.get(EngineeringKnowledgeGraphNode, stale.id)
    refreshed_cleanup = await db.get(EngineeringKnowledgeGraphNode, cleanup_target.id)
    assert invalidation.matched_count == 1
    assert cleanup.matched_count == 1
    assert refreshed is not None
    assert refreshed.status == "stale"
    assert refreshed.properties_json["lifecycle"]["superseded_by_node_id"] == replacement.id
    assert refreshed.properties_json["lifecycle_history"]
    assert refreshed_cleanup is not None
    assert refreshed_cleanup.status == "retracted"
    assert refreshed_cleanup.properties_json["lifecycle"]["deleted_source_cleanup"] is True

    retrieved = await search_engineering_knowledge_graph(db, query="CVE-2026-353", limit=10)
    keys = {item["node_key"] for item in retrieved["results"]}
    assert stale.node_key not in keys
    assert cleanup_target.node_key not in keys
    assert replacement.node_key in keys
