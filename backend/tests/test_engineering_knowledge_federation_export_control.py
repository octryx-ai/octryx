from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import User
from app.services.engineering_knowledge import (
    KnowledgePackageValidationError,
    create_signed_engineering_knowledge_package,
    preview_federation_export_control,
    upsert_engineering_knowledge_node,
    validate_engineering_knowledge_package_payload,
)

SIGNING_KEY = "local-test-signing-key-32"


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _node(db, admin: User, **overrides):
    payload = {
        "node_type": "fix_pattern",
        "node_key": overrides.pop("node_key", "federation-export-fact"),
        "display_name": overrides.pop("display_name", "Federation export fact"),
        "summary": overrides.pop("summary", "Reviewed source-backed engineering fact."),
        "trust_level": overrides.pop("trust_level", "gold"),
        "classification": overrides.pop("classification", "internal"),
        "source_refs": overrides.pop("source_refs", [{"source_type": "jira", "source_ref": "OCX-100"}]),
        "properties": overrides.pop("properties", {}),
        "created_by_user_id": admin.id,
        **overrides,
    }
    node = await upsert_engineering_knowledge_node(db, **payload)
    await db.commit()
    return node


async def test_federation_export_blocks_secret_values(db):
    admin = await _admin(db)
    node = await _node(
        db,
        admin,
        node_key="federation-secret-value",
        summary="Do not export Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    )

    with pytest.raises(KnowledgePackageValidationError, match="secret-looking values"):
        await create_signed_engineering_knowledge_package(
            db,
            node_ids=[node.id],
            publisher_instance_id="octryx-local",
            signing_key=SIGNING_KEY,
        )


async def test_federation_export_redacts_pii_jira_urls_and_repository_paths(db):
    admin = await _admin(db)
    node = await _node(
        db,
        admin,
        node_key="federation-pii-redaction",
        summary=(
            "Contact alice@example.com about OCX-123 at "
            "https://jira.example.invalid/browse/OCX-123 in src/main/java/com/acme/Fix.java"
        ),
    )

    package = await create_signed_engineering_knowledge_package(
        db,
        node_ids=[node.id],
        publisher_instance_id="octryx-local",
        signing_key=SIGNING_KEY,
    )

    fact = package["facts"]["nodes"][0]
    assert validate_engineering_knowledge_package_payload(package) == []
    assert "[EMAIL]" in fact["summary"]
    assert "[JIRA_KEY]" in fact["summary"]
    assert "[URL]" in fact["summary"]
    assert "[REPOSITORY_PATH]" in fact["summary"]
    assert fact["classification"] == "internal"
    assert fact["export_control"]["action"] == "redacted"
    assert {"pii:email", "jira_key", "url", "repository_path"}.issubset(
        set(fact["export_control"]["redaction_types"])
    )


async def test_federation_export_blocks_customer_specific_without_review(db):
    admin = await _admin(db)
    node = await _node(
        db,
        admin,
        node_key="federation-customer-specific",
        summary="ACME Bank rollout finding.",
        properties={"customer_name": "ACME Bank"},
    )

    with pytest.raises(KnowledgePackageValidationError, match="Human review required"):
        await create_signed_engineering_knowledge_package(
            db,
            node_ids=[node.id],
            publisher_instance_id="octryx-local",
            signing_key=SIGNING_KEY,
            export_policy={"customer_terms": ["ACME Bank"], "allow_with_review": ["customer_specific"]},
        )


async def test_federation_export_allows_confidential_with_reviewer_approval(db):
    admin = await _admin(db)
    node = await _node(
        db,
        admin,
        node_key="federation-confidential-approved",
        classification="confidential",
        summary="Reviewed confidential implementation pattern.",
    )

    package = await create_signed_engineering_knowledge_package(
        db,
        node_ids=[node.id],
        publisher_instance_id="octryx-local",
        signing_key=SIGNING_KEY,
        export_policy={
            "allow_with_review": ["confidential"],
            "review": {"approved": True, "reviewer_role": "security"},
        },
    )

    fact = package["facts"]["nodes"][0]
    assert validate_engineering_knowledge_package_payload(package) == []
    assert fact["classification"] == "internal"
    assert fact["export_control"]["action"] == "redacted"
    assert "confidential" in fact["export_control"]["labels"]
    assert any("Reviewer approval accepted" in reason for reason in fact["export_control"]["reasons"])


async def test_federation_export_preview_returns_redacted_safe_decisions(db):
    admin = await _admin(db)
    node = await _node(
        db,
        admin,
        node_key="federation-preview-redacted",
        summary="Notify jane.doe@example.com about OCX-456.",
    )

    preview = await preview_federation_export_control(db, node_ids=[node.id])

    assert preview["node_count"] == 1
    assert preview["counts"]["redacted"] == 1
    assert preview["decisions"][0]["action"] == "redacted"
    assert "pii:email" in preview["decisions"][0]["redaction_types"]
    assert "[EMAIL]" in preview["preview"][0]["summary"]
    assert "jane.doe@example.com" not in preview["preview"][0]["summary"]
