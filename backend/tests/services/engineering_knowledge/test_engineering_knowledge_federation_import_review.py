from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.models import EngineeringKnowledgeFederationPackage, EngineeringKnowledgeGraphNode, User
from app.services.engineering_knowledge import (
    create_engineering_knowledge_federation_feed,
    create_signed_engineering_knowledge_package,
    import_signed_engineering_knowledge_package,
    review_imported_engineering_knowledge_package,
    search_engineering_knowledge_graph,
    upsert_engineering_knowledge_node,
)
from app.time_utils import utc_now

SIGNING_KEY = "local-test-signing-key-32"


async def _feed(db, admin: User):
    return await create_engineering_knowledge_federation_feed(
        db,
        payload={"name": f"Import Review Feed {utc_now().timestamp()}", "publisher_instance_id": "publisher-alpha"},
        current_user=admin,
    )


async def _source_node(db, admin: User, *, key: str, **overrides):
    node = await upsert_engineering_knowledge_node(
        db,
        node_type=overrides.pop("node_type", "fix_pattern"),
        node_key=key,
        display_name=overrides.pop("display_name", f"Imported fact {key}"),
        summary=overrides.pop("summary", "Remote reviewed remediation pattern."),
        trust_level=overrides.pop("trust_level", "gold"),
        classification=overrides.pop("classification", "internal"),
        properties=overrides.pop("properties", {}),
        source_refs=overrides.pop("source_refs", [{"source_type": "jira", "source_ref": f"OCX-{key}"}]),
        created_by_user_id=admin.id,
        **overrides,
    )
    await db.commit()
    return node


async def _package_from_node(db, node: EngineeringKnowledgeGraphNode, *, package_id: str, valid_until=None):
    return await create_signed_engineering_knowledge_package(
        db,
        node_ids=[node.id],
        publisher_instance_id="publisher-alpha",
        signing_key=SIGNING_KEY,
        signing_key_id="alpha-key",
        package_id=package_id,
        valid_until=valid_until,
    )


async def _import_package(db, admin: User, package: dict):
    feed = await _feed(db, admin)
    imported = await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed["id"],
        package=package,
        verification_key=SIGNING_KEY,
        current_user=admin,
    )
    await db.commit()
    return imported


async def test_import_conflict_detection_classifies_versions_vulnerability_and_stale_package(db, auth_user):
    remote = await _source_node(
        db,
        auth_user,
        key="federation-review-conflict",
        summary="Upgrade CVE package to 2.0.",
        properties={"version": "2.0", "baseline": "java25", "cve": "CVE-2026-358", "fix": "upgrade-to-2"},
    )
    package = await _package_from_node(
        db,
        remote,
        package_id="conflict-package",
        valid_until=utc_now() - timedelta(days=1),
    )
    await _source_node(
        db,
        auth_user,
        key="federation-review-conflict",
        summary="Keep package on 1.0 with compensating control.",
        properties={"version": "1.0", "baseline": "java21", "cve": "CVE-2026-358", "fix": "compensating-control"},
    )

    imported = await _import_package(db, auth_user, package)

    conflicts = {item["conflict"] for item in imported["dry_run"]["conflicts"]}
    assert {"version_conflict", "incompatible_baseline", "vulnerability_fix_disagreement", "stale_package"}.issubset(
        conflicts
    )
    assert imported["package"]["review_status"] == "pending_review"


async def test_import_review_accept_lower_trust_creates_namespaced_imported_retrieval_fact(db, auth_user):
    remote = await _source_node(db, auth_user, key="federation-review-trust-downgrade")
    package = await _package_from_node(db, remote, package_id="trust-downgrade-package")
    imported = await _import_package(db, auth_user, package)

    review = await review_imported_engineering_knowledge_package(
        db,
        package_record_id=imported["package"]["id"],
        action="accept_lower_trust",
        payload={"reason": "External publisher accepted at lower local trust", "local_trust_level": "silver"},
        current_user=auth_user,
    )
    await db.commit()

    node = (
        await db.execute(
            select(EngineeringKnowledgeGraphNode).where(
                EngineeringKnowledgeGraphNode.node_key
                == "federated:publisher-alpha:federation-review-trust-downgrade"
            )
        )
    ).scalar_one()
    federation = node.properties_json["federation"]
    retrieval = await search_engineering_knowledge_graph(
        db,
        query="trust-downgrade",
        include_silver=True,
        limit=5,
    )

    assert review["package"]["review_status"] == "accepted_lower_trust"
    assert node.trust_level == "silver"
    assert federation["origin"] == "imported"
    assert federation["publisher_instance_id"] == "publisher-alpha"
    assert federation["original_trust_level"] == "gold"
    assert federation["local_trust_level"] == "silver"
    imported_results = [item for item in retrieval["results"] if item["origin"] == "imported"]
    assert imported_results
    assert imported_results[0]["federation"]["publisher_instance_id"] == "publisher-alpha"


async def test_import_review_quarantine_duplicate_merge_and_local_override_do_not_create_graph_nodes(db, auth_user):
    remote = await _source_node(db, auth_user, key="federation-review-nonmutating")
    package = await _package_from_node(db, remote, package_id="nonmutating-package")
    imported = await _import_package(db, auth_user, package)
    before_count = (await db.execute(select(func.count(EngineeringKnowledgeGraphNode.id)))).scalar_one()

    quarantine = await review_imported_engineering_knowledge_package(
        db,
        package_record_id=imported["package"]["id"],
        action="quarantine",
        payload={"reason": "Needs publisher clarification"},
        current_user=auth_user,
    )
    duplicate = await review_imported_engineering_knowledge_package(
        db,
        package_record_id=imported["package"]["id"],
        action="merge_duplicate",
        payload={"reason": "Duplicate of local reviewed fact"},
        current_user=auth_user,
    )
    local_override = await review_imported_engineering_knowledge_package(
        db,
        package_record_id=imported["package"]["id"],
        action="local_override",
        payload={"reason": "Local Gold remains authoritative"},
        current_user=auth_user,
    )
    await db.commit()
    after_count = (await db.execute(select(func.count(EngineeringKnowledgeGraphNode.id)))).scalar_one()
    record = await db.get(EngineeringKnowledgeFederationPackage, imported["package"]["id"])

    assert quarantine["package"]["review_status"] == "quarantined"
    assert duplicate["package"]["review_status"] == "merged_duplicate"
    assert local_override["package"]["review_status"] == "local_override"
    assert record.review_status == "local_override"
    assert before_count == after_count
