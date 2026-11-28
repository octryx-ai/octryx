from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import EngineeringKnowledgeGraphNode
from app.services.engineering_knowledge import (
    PACKAGE_SCHEMA_VERSION,
    KnowledgePackageValidationError,
    create_signed_engineering_knowledge_package,
    dry_run_import_engineering_knowledge_package,
    upsert_engineering_knowledge_edge,
    upsert_engineering_knowledge_node,
    validate_engineering_knowledge_package_payload,
    verify_engineering_knowledge_package_signature,
)

SIGNING_KEY = "local-test-signing-key-32"


async def test_signed_knowledge_package_creation_signature_and_dry_run_import(db, auth_user):
    library = await upsert_engineering_knowledge_node(
        db,
        node_type="library",
        node_key="pkg-signature-lib",
        display_name="Package signature library",
        summary="Reviewed package export source.",
        trust_level="gold",
        classification="internal",
        source_refs=[{"source_type": "pull_request", "source_ref": "PR-package-1", "title": "Reviewed fix"}],
        properties={"version": "1.2.3"},
        created_by_user_id=auth_user.id,
    )
    fix = await upsert_engineering_knowledge_node(
        db,
        node_type="fix_pattern",
        node_key="pkg-signature-fix",
        display_name="Package signature fix",
        summary="Use the verified remediation.",
        trust_level="gold",
        classification="internal",
        source_refs=[{"source_type": "jenkins", "source_ref": "job/package/1"}],
        properties={"command": "mvn test"},
        created_by_user_id=auth_user.id,
    )
    await upsert_engineering_knowledge_edge(
        db,
        edge_type="fixed_by",
        source_node_id=library.id,
        target_node_id=fix.id,
        trust_level="gold",
        classification="internal",
        source_refs=[{"source_type": "pull_request", "source_ref": "PR-package-1"}],
        created_by_user_id=auth_user.id,
    )
    await db.commit()

    before_count = (
        await db.execute(select(func.count(EngineeringKnowledgeGraphNode.id)))
    ).scalar_one()
    package = await create_signed_engineering_knowledge_package(
        db,
        node_ids=[library.id, fix.id],
        publisher_instance_id="octryx-local",
        signing_key=SIGNING_KEY,
        signing_key_id="local-key",
        usage_policy={"allowed_use": "engineering_agent_context", "redistribution": "review_required"},
    )

    assert package["schema_version"] == PACKAGE_SCHEMA_VERSION
    assert package["publisher"]["instance_id"] == "octryx-local"
    assert package["redaction"]["raw_content_included"] is False
    assert package["facts"]["nodes"][0]["source_evidence"]
    assert package["facts"]["edges"][0]["type"] == "fixed_by"
    assert package["signature"]["algorithm"] == "hmac-sha256"
    assert validate_engineering_knowledge_package_payload(package) == []

    signature = verify_engineering_knowledge_package_signature(package, signing_key=SIGNING_KEY)
    assert signature["valid"] is True

    dry_run = await dry_run_import_engineering_knowledge_package(db, package, verification_key=SIGNING_KEY)
    after_count = (
        await db.execute(select(func.count(EngineeringKnowledgeGraphNode.id)))
    ).scalar_one()
    assert dry_run["status"] == "ready"
    assert dry_run["mutated"] is False
    assert dry_run["node_count"] == 2
    assert dry_run["edge_count"] == 1
    assert after_count == before_count
    assert {conflict["conflict"] for conflict in dry_run["conflicts"]} == {"duplicate"}


async def test_package_verification_rejects_invalid_signature_and_schema(db, auth_user):
    node = await upsert_engineering_knowledge_node(
        db,
        node_type="framework",
        node_key="pkg-invalid-schema",
        display_name="Invalid schema framework",
        summary="Reviewed framework fact.",
        trust_level="gold",
        classification="internal",
        source_refs=[{"source_type": "url", "source_ref": "https://example.test/framework"}],
        created_by_user_id=auth_user.id,
    )
    await db.commit()
    package = await create_signed_engineering_knowledge_package(
        db,
        node_ids=[node.id],
        publisher_instance_id="octryx-local",
        signing_key=SIGNING_KEY,
    )

    tampered = dict(package)
    tampered["trust_level"] = "official"
    invalid_signature = verify_engineering_knowledge_package_signature(tampered, signing_key=SIGNING_KEY)
    assert invalid_signature["valid"] is False

    invalid_schema = dict(package)
    invalid_schema["schema_version"] = "engineering_knowledge_package.v999"
    dry_run = await dry_run_import_engineering_knowledge_package(db, invalid_schema, verification_key=SIGNING_KEY)
    assert dry_run["status"] == "blocked"
    assert {error["code"] for error in dry_run["errors"]} >= {
        "unsupported_schema_version",
        "invalid_signature",
    }


async def test_package_export_blocks_unsafe_or_non_exportable_content(db, auth_user):
    secret_node = await upsert_engineering_knowledge_node(
        db,
        node_type="decision",
        node_key="pkg-secret-decision",
        display_name="Secret decision",
        summary="Should not be exported.",
        trust_level="gold",
        classification="secret",
        source_refs=[{"source_type": "session", "source_ref": "sensitive-session"}],
        created_by_user_id=auth_user.id,
    )
    await db.commit()

    with pytest.raises(KnowledgePackageValidationError, match="non-exportable classification"):
        await create_signed_engineering_knowledge_package(
            db,
            node_ids=[secret_node.id],
            publisher_instance_id="octryx-local",
            signing_key=SIGNING_KEY,
        )

    unsafe_package = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": "unsafe-package",
        "publisher": {"instance_id": "octryx-local"},
        "created_at": "2026-06-21T00:00:00+00:00",
        "classification": "internal",
        "trust_level": "gold",
        "facts": {
            "nodes": [
                {
                    "fact_kind": "node",
                    "type": "fix_pattern",
                    "key": "unsafe",
                    "status": "active",
                    "classification": "internal",
                    "trust_level": "gold",
                    "properties": {"raw_log": "must not leave instance"},
                    "content_digest": "invalid",
                }
            ],
            "edges": [],
        },
    }
    errors = validate_engineering_knowledge_package_payload(unsafe_package, raise_on_error=False)
    assert "unsafe_payload" in {error["code"] for error in errors}
