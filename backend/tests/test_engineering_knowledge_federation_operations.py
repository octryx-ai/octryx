from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    AuditLog,
    EngineeringKnowledgeFederationFeed,
    EngineeringKnowledgeGraphNode,
    User,
)
from app.services.engineering_knowledge import (
    create_engineering_knowledge_federation_feed,
    create_signed_engineering_knowledge_package,
    disable_engineering_knowledge_federation_feed,
    get_engineering_knowledge_federation_dashboard,
    get_federation_usage_impact,
    import_signed_engineering_knowledge_package,
    record_federated_knowledge_usage,
    review_imported_engineering_knowledge_package,
    upsert_engineering_knowledge_node,
)

SIGNING_KEY = "local-test-signing-key-32"


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _feed(db, admin: User, *, name: str = "Federation Ops Feed"):
    return await create_engineering_knowledge_federation_feed(
        db,
        payload={"name": name, "feed_type": "subscriber", "publisher_instance_id": "publisher-alpha"},
        current_user=admin,
    )


async def _source_node(db, admin: User, *, key: str):
    node = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key=key,
        display_name=f"Federation operations {key}",
        summary="Federated operational evidence for coding agents.",
        trust_level="gold",
        classification="internal",
        source_refs=[{"source_type": "jira", "source_ref": f"OCX-{key}"}],
        created_by_user_id=admin.id,
    )
    await db.commit()
    return node


async def _signed_package(db, admin: User, *, package_id: str, key: str):
    node = await _source_node(db, admin, key=key)
    return await create_signed_engineering_knowledge_package(
        db,
        node_ids=[node.id],
        publisher_instance_id="publisher-alpha",
        signing_key=SIGNING_KEY,
        signing_key_id="alpha-key",
        package_id=package_id,
    )


async def test_retraction_propagates_to_accepted_imported_graph_facts(db):
    admin = await _admin(db)
    feed = await _feed(db, admin, name="Retraction Propagation Feed")
    package = await _signed_package(db, admin, package_id="ops-package-to-retract", key="ops-retract-fact")
    imported = await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed["id"],
        package=package,
        verification_key=SIGNING_KEY,
        current_user=admin,
    )
    await review_imported_engineering_knowledge_package(
        db,
        package_record_id=imported["package"]["id"],
        action="accept",
        payload={"reason": "Accepted imported fact for operational impact test"},
        current_user=admin,
    )
    retraction_node = await _source_node(db, admin, key="ops-retraction-fact")
    retraction_package = await create_signed_engineering_knowledge_package(
        db,
        node_ids=[retraction_node.id],
        publisher_instance_id="publisher-alpha",
        signing_key=SIGNING_KEY,
        signing_key_id="alpha-key",
        package_id="ops-retraction-package",
        retractions=[{"package_id": "ops-package-to-retract", "reason": "Publisher revoked fact"}],
    )

    result = await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed["id"],
        package=retraction_package,
        verification_key=SIGNING_KEY,
        current_user=admin,
    )
    await db.commit()

    imported_node = (
        await db.execute(
            select(EngineeringKnowledgeGraphNode).where(
                EngineeringKnowledgeGraphNode.node_key == "federated:publisher-alpha:ops-retract-fact"
            )
        )
    ).scalar_one()
    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "engineering_knowledge_federation.retraction_propagated")
        )
    ).scalar_one()

    assert result["sync_run"]["operation"] == "retraction_sync"
    assert result["retractions"]["retracted_count"] == 1
    assert result["retractions"]["affected_fact_ids"] == [imported_node.id]
    assert result["retractions"]["required_action"] == "review_retracted_imported_facts"
    assert imported_node.status == "retracted"
    assert imported_node.properties_json["federation"]["import_status"] == "retracted"
    assert audit.details["affected_fact_ids"] == [imported_node.id]


async def test_emergency_feed_disable_blocks_imports_and_records_audit(db):
    admin = await _admin(db)
    feed = await _feed(db, admin, name="Emergency Disable Feed")

    result = await disable_engineering_knowledge_federation_feed(
        db,
        feed_id=feed["id"],
        reason="Publisher compromise suspected",
        current_user=admin,
    )
    package = await _signed_package(db, admin, package_id="disabled-feed-package", key="disabled-feed-fact")

    try:
        await import_signed_engineering_knowledge_package(
            db,
            feed_id=feed["id"],
            package=package,
            verification_key=SIGNING_KEY,
            current_user=admin,
        )
    except HTTPException as exc:
        blocked = exc
    else:
        raise AssertionError("disabled feed accepted an import")
    await db.commit()

    persisted = await db.get(EngineeringKnowledgeFederationFeed, feed["id"])
    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "engineering_knowledge_federation.feed_emergency_disabled")
        )
    ).scalar_one()

    assert result["feed"]["status"] == "disabled"
    assert result["sync_run"]["operation"] == "emergency_disable"
    assert persisted.status == "disabled"
    assert blocked.status_code == 409
    assert audit.details["reason"] == "Publisher compromise suspected"


async def test_import_failures_and_policy_blocks_are_visible_in_federation_dashboard(db):
    admin = await _admin(db)
    feed = await _feed(db, admin, name="Failure Visibility Feed")
    package = await _signed_package(db, admin, package_id="failure-visibility-package", key="failure-visibility")
    package["classification"] = "secret"

    result = await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed["id"],
        package=package,
        verification_key="wrong-signing-key",
        current_user=admin,
    )
    await db.commit()
    dashboard = await get_engineering_knowledge_federation_dashboard(db, limit=20)
    audit_actions = {
        row.action
        for row in (await db.execute(select(AuditLog).where(AuditLog.resource_id == result["package"]["id"]))).scalars()
    }

    assert result["sync_run"]["status"] == "failed"
    assert dashboard["summary"]["failed_sync_count"] >= 1
    assert dashboard["operations"]["failed_import_count"] >= 1
    assert dashboard["operations"]["signature_failure_count"] >= 1
    assert dashboard["operations"]["policy_blocked_count"] >= 1
    assert "engineering_knowledge_federation.policy_blocked" in audit_actions


async def test_federated_usage_impact_records_runs_sessions_and_fact_ids(db):
    admin = await _admin(db)

    recorded = await record_federated_knowledge_usage(
        db,
        package_record_id="package-record-ops",
        package_id="ops-usage-package",
        run_id="agent-run-ops",
        session_id="session-ops",
        fact_ids=["fact-a", "fact-b"],
        current_user=admin,
    )
    await db.commit()
    impact = await get_federation_usage_impact(db, package_id="ops-usage-package", limit=10)
    dashboard = await get_engineering_knowledge_federation_dashboard(db, limit=20)

    assert recorded["run_id"] == "agent-run-ops"
    assert impact["count"] == 1
    assert impact["usage_events"][0]["fact_ids"] == ["fact-a", "fact-b"]
    assert any(event["run_id"] == "agent-run-ops" for event in dashboard["operations"]["usage_events"])
