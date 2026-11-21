from __future__ import annotations

from sqlalchemy import select

from app.models import Project, User
from app.services.engineering_knowledge import (
    evaluate_engineering_knowledge_node_quality,
    get_engineering_knowledge_quality_dashboard,
    upsert_engineering_knowledge_edge,
    upsert_engineering_knowledge_node,
)


async def _admin_and_project(db) -> tuple[User, Project]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    return admin, project


async def test_engineering_knowledge_quality_gates_detect_evidence_contradictions_and_retrieval(db):
    admin, _project = await _admin_and_project(db)
    good = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="quality-good-spring-fix",
        display_name="Quality good Spring fix",
        summary="Use the reviewed Spring fix with Jenkins verification.",
        trust_level="gold",
        classification="internal",
        source_refs=[{"source_type": "jenkins", "source_ref": "job/quality/1"}],
        created_by_user_id=admin.id,
    )
    weak = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="quality-weak-spring-fix",
        display_name="Quality weak Spring fix",
        summary="Unsupported fix.",
        status="stale",
        trust_level="bronze",
        source_refs=[],
        created_by_user_id=admin.id,
    )
    conflicting = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="quality-conflicting-spring-fix",
        display_name="Quality conflicting Spring fix",
        summary="Conflicting fix.",
        trust_level="gold",
        source_refs=[{"source_type": "pull_request", "source_ref": "PR-conflict"}],
        created_by_user_id=admin.id,
    )
    await upsert_engineering_knowledge_edge(
        db,
        edge_type="conflicts_with",
        source_node_id=weak.id,
        target_node_id=conflicting.id,
        status="active",
        trust_level="gold",
        created_by_user_id=admin.id,
    )
    await db.commit()

    good_report = await evaluate_engineering_knowledge_node_quality(db, good)
    weak_report = await evaluate_engineering_knowledge_node_quality(db, weak)
    dashboard = await get_engineering_knowledge_quality_dashboard(db, limit=20)

    assert good_report["passed"] is True
    weak_blockers = {gate["key"] for gate in weak_report["blockers"]}
    assert {"evidence_coverage", "freshness", "trust_level", "contradiction_detection"} <= weak_blockers
    assert dashboard["quality"]["evaluated_count"] >= 2
    assert dashboard["usage"]["retrieval_miss_instrumented"] is False
    assert any(item["key"] == "vulnerability_fix" for item in dashboard["evaluation_scenarios"])
