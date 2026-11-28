from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import EngineeringKnowledgeFederationPackage, EngineeringKnowledgeFederationSyncRun, User
from app.services.engineering_knowledge import (
    create_engineering_knowledge_federation_feed,
    create_signed_engineering_knowledge_package,
    import_signed_engineering_knowledge_package,
    publish_signed_engineering_knowledge_package,
    record_engineering_knowledge_federation_sync_failure,
    upsert_engineering_knowledge_node,
)

SIGNING_KEY = "local-test-signing-key-32"


async def _source_node(db, admin: User, key: str = "federation-source"):
    node = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key=key,
        display_name=f"Federated fix {key}",
        summary="Reviewed engineering knowledge fact for federation.",
        trust_level="gold",
        classification="internal",
        source_refs=[{"source_type": "pull_request", "source_ref": f"PR-{key}"}],
        created_by_user_id=admin.id,
    )
    await db.commit()
    return node


async def _signed_package(db, admin: User, *, package_id: str = "federation-package", policy_note: str = "review"):
    node = await _source_node(db, admin, key=f"{package_id}-{policy_note}")
    return await create_signed_engineering_knowledge_package(
        db,
        node_ids=[node.id],
        publisher_instance_id="publisher-alpha",
        signing_key=SIGNING_KEY,
        signing_key_id="alpha-key",
        package_id=package_id,
        usage_policy={"allowed_use": "engineering_agent_context", "redistribution": policy_note},
    )


async def test_publish_signed_package_tracks_versions_duplicates_and_sync_runs(db, auth_user):
    package = await _signed_package(db, auth_user)

    created = await publish_signed_engineering_knowledge_package(db, package=package, current_user=auth_user)
    duplicate = await publish_signed_engineering_knowledge_package(db, package=package, current_user=auth_user)
    updated_package = await _signed_package(db, auth_user, package_id=package["package_id"], policy_note="updated")
    updated = await publish_signed_engineering_knowledge_package(db, package=updated_package, current_user=auth_user)
    await db.commit()

    records = (
        (
            await db.execute(
                select(EngineeringKnowledgeFederationPackage)
                .where(EngineeringKnowledgeFederationPackage.direction == "published")
                .order_by(EngineeringKnowledgeFederationPackage.version.asc())
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (
            await db.execute(
                select(EngineeringKnowledgeFederationSyncRun).order_by(EngineeringKnowledgeFederationSyncRun.started_at.asc())
            )
        )
        .scalars()
        .all()
    )

    assert created["action"] == "created"
    assert duplicate["action"] == "duplicate"
    assert updated["action"] == "updated"
    assert [record.version for record in records] == [1, 2]
    assert [record.status for record in records] == ["published", "published"]
    assert [run.operation for run in runs] == ["publish", "duplicate", "updated"]
    assert all(run.status == "success" for run in runs)


async def test_publish_requires_signed_package(db, auth_user):
    package = await _signed_package(db, auth_user)
    package.pop("signature", None)

    with pytest.raises(HTTPException) as exc_info:
        await publish_signed_engineering_knowledge_package(db, package=package, current_user=auth_user)

    assert exc_info.value.status_code == 400
    assert "Signed Engineering Knowledge package" in str(exc_info.value.detail)


async def test_import_signed_package_records_pending_review_and_feed_health(db, auth_user):
    feed = await create_engineering_knowledge_federation_feed(
        db,
        payload={
            "name": "Publisher Alpha",
            "feed_type": "subscriber",
            "publisher_instance_id": "publisher-alpha",
            "verification_key_ref": "secret://engineering-knowledge/publisher-alpha",
        },
        current_user=auth_user,
    )
    package = await _signed_package(db, auth_user)

    imported = await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed["id"],
        package=package,
        verification_key=SIGNING_KEY,
        current_user=auth_user,
    )
    await db.commit()

    record = imported["package"]
    sync_run = imported["sync_run"]
    assert imported["action"] == "created"
    assert imported["dry_run"]["status"] == "ready"
    assert record["direction"] == "imported"
    assert record["status"] == "pending_review"
    assert record["review_status"] == "pending_review"
    assert sync_run["operation"] == "import"
    assert sync_run["status"] == "success"


async def test_import_retraction_marks_previous_imported_package_retracted(db, auth_user):
    feed = await create_engineering_knowledge_federation_feed(
        db,
        payload={"name": "Retraction Feed", "feed_type": "subscriber", "publisher_instance_id": "publisher-alpha"},
        current_user=auth_user,
    )
    package = await _signed_package(db, auth_user, package_id="package-to-retract")
    await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed["id"],
        package=package,
        verification_key=SIGNING_KEY,
        current_user=auth_user,
    )
    retraction_node = await _source_node(db, auth_user, key="retraction-package-source")
    retraction = await create_signed_engineering_knowledge_package(
        db,
        node_ids=[retraction_node.id],
        publisher_instance_id="publisher-alpha",
        signing_key=SIGNING_KEY,
        signing_key_id="alpha-key",
        package_id="retraction-package",
        retractions=[{"package_id": "package-to-retract", "reason": "Replaced by newer package"}],
    )

    result = await import_signed_engineering_knowledge_package(
        db,
        feed_id=feed["id"],
        package=retraction,
        verification_key=SIGNING_KEY,
        current_user=auth_user,
    )
    await db.commit()

    original = (
        await db.execute(
            select(EngineeringKnowledgeFederationPackage).where(
                EngineeringKnowledgeFederationPackage.package_id == "package-to-retract",
                EngineeringKnowledgeFederationPackage.direction == "imported",
            )
        )
    ).scalar_one()
    assert original.status == "retracted"
    assert original.review_status == "retracted"
    assert result["sync_run"]["operation"] == "retraction_sync"
    assert result["retractions"]["retracted_count"] == 1


async def test_sync_failure_updates_feed_state(db, auth_user):
    feed = await create_engineering_knowledge_federation_feed(
        db,
        payload={"name": "Failure Feed", "feed_type": "subscriber", "publisher_instance_id": "publisher-alpha"},
        current_user=auth_user,
    )

    result = await record_engineering_knowledge_federation_sync_failure(
        db,
        feed_id=feed["id"],
        error="Remote feed returned 503",
        operation="poll",
        current_user=auth_user,
    )
    await db.commit()

    assert result["sync_run"]["status"] == "failed"
    assert result["sync_run"]["errors"][0]["code"] == "sync_failed"
    assert result["feed"]["last_sync_status"] == "failed"
    assert result["feed"]["last_error"] == "Remote feed returned 503"
