from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.models import AuditLog, BudgetPolicy, ExecPolicyConfig, IdentityProvider, Project, User
from app.services.admin.panel import admin_panel_service, admin_secret_service
from app.services.budget import upsert_budget_policy
from app.services.feature_flag import delete_feature_flag, upsert_feature_flag
from app.services.oidc import serialize_identity_provider, upsert_identity_provider
from app.services.secret import set_secret_value
from app.time_utils import utc_now


async def _admin_user_id(db) -> str:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    return admin.id


async def _audit_log(db, action: str, resource_id: str | None = None) -> AuditLog:
    query = select(AuditLog).where(AuditLog.action == action)
    if resource_id is not None:
        query = query.where(AuditLog.resource_id == resource_id)
    return (await db.execute(query.order_by(AuditLog.created_at.desc()))).scalars().first()


def _serialize_budget_policy(policy: BudgetPolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "name": policy.name or "",
        "userId": policy.user_id or "",
        "projectId": policy.project_id or "",
        "dailyRequestLimit": int(policy.daily_request_limit) if policy.daily_request_limit is not None else None,
        "dailyTokenLimit": int(policy.daily_token_limit) if policy.daily_token_limit is not None else None,
        "dailyCostLimit": float(policy.daily_cost_limit) if policy.daily_cost_limit is not None else None,
        "warnAtPercent": int(policy.warn_at_percent or 80),
        "blockAtPercent": int(policy.block_at_percent or 100),
        "isActive": bool(policy.is_active),
    }


def _serialize_exec_policy_config(config: ExecPolicyConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "name": config.name or "",
        "projectId": config.project_id or "",
        "priority": int(config.priority or 0),
        "isActive": bool(config.is_active),
        "config": dict(config.config_json or {}),
    }


def _assert_no_governance_secret_values(details: dict[str, Any], *forbidden_values: str) -> None:
    details_text = str(details)
    for value in forbidden_values:
        assert value not in details_text


@pytest.mark.asyncio
async def test_budget_policy_mutations_record_audit_logs(db):
    admin_id = await _admin_user_id(db)
    budget = await upsert_budget_policy(
        db,
        payload={
            "name": "Governance Audit Budget",
            "user_id": admin_id,
            "daily_request_limit": 25,
            "warn_at_percent": 80,
            "block_at_percent": 100,
            "is_active": True,
        },
        serialize_policy=_serialize_budget_policy,
        actor_user_id=admin_id,
    )

    budget_audit = await _audit_log(db, "admin.governance.budget_policy.saved", budget["id"])
    assert budget_audit is not None
    assert budget_audit.user_id == admin_id
    assert budget_audit.resource_type == "budget_policy"
    assert set(budget_audit.details["changed_keys"]) >= {"id", "name", "user_id", "daily_request_limit"}
    assert budget_audit.details["operation"] == "upsert_budget_policy"
    assert "daily_request_limit" in budget_audit.details["payload_keys"]


@pytest.mark.asyncio
async def test_identity_provider_mutation_records_secret_safe_audit_log(db):
    admin_id = await _admin_user_id(db)
    raw_secret = "oidc-client-secret-for-audit"
    created = await upsert_identity_provider(
        db,
        payload={
            "name": "Governance OIDC",
            "provider_type": "oidc",
            "issuer_url": "https://issuer.example.test",
            "client_id": "governance-client",
            "client_secret": raw_secret,
            "scopes": ["openid", "email"],
            "is_active": True,
        },
        serialize_provider=serialize_identity_provider,
        actor_user_id=admin_id,
    )

    provider = await db.get(IdentityProvider, created["id"])
    assert provider is not None
    audit = await _audit_log(db, "admin.security.identity_provider.saved", created["id"])
    assert audit is not None
    assert audit.user_id == admin_id
    assert audit.resource_type == "identity_provider"
    assert set(audit.details["changed_keys"]) >= {"id", "name", "client_id", "clientAuthConfigured"}
    assert audit.details["operation"] == "upsert_identity_provider"
    assert "client_secret" in audit.details["payload_keys"]
    assert audit.details["after"]["clientAuthConfigured"] is True
    _assert_no_governance_secret_values(audit.details, raw_secret, provider.client_secret_secret_ref or "")


@pytest.mark.asyncio
async def test_exec_policy_mutations_record_audit_logs(db):
    admin_id = await _admin_user_id(db)
    await admin_panel_service.update_global_exec_policy_payload(
        db,
        {"always_deny_patterns": [r"\bhalt\b"], "shell_risk_operators": ["&&"]},
        actor_user_id=admin_id,
    )
    global_audit = await _audit_log(db, "admin.governance.exec_policy.global_updated")
    assert global_audit is not None
    assert global_audit.user_id == admin_id
    assert global_audit.resource_type == "exec_policy_config"
    assert "config" in global_audit.details["changed_keys"]
    assert global_audit.details["operation"] == "update_global_exec_policy_payload"

    project = (await db.execute(select(Project).order_by(Project.created_at.asc()))).scalars().first()
    assert project is not None
    created = await admin_panel_service.create_exec_policy_payload(
        db,
        payload={
            "name": "Governance Project Exec Policy",
            "projectId": project.id,
            "priority": 75,
            "isActive": True,
            "config": {"diagnosis_read_only_commands": ["ls"]},
        },
        serialize_exec_policy_config=_serialize_exec_policy_config,
        actor_user_id=admin_id,
    )
    created_audit = await _audit_log(db, "admin.governance.exec_policy.created", created["id"])
    assert created_audit is not None
    assert set(created_audit.details["changed_keys"]) >= {"id", "name", "project_id", "config"}
    assert created_audit.details["operation"] == "create_exec_policy_payload"

    updated = await admin_panel_service.update_exec_policy_payload(
        db,
        config_id=created["id"],
        payload={
            "name": "Governance Project Exec Policy Updated",
            "projectId": project.id,
            "priority": 80,
            "isActive": True,
            "config": {"diagnosis_read_only_commands": ["ls", "cat"]},
        },
        serialize_exec_policy_config=_serialize_exec_policy_config,
        actor_user_id=admin_id,
    )
    updated_audit = await _audit_log(db, "admin.governance.exec_policy.updated", updated["id"])
    assert updated_audit is not None
    assert set(updated_audit.details["changed_keys"]) >= {"name", "priority", "config"}
    assert updated_audit.details["operation"] == "update_exec_policy_payload"

    result = await admin_panel_service.delete_exec_policy_payload(
        db,
        config_id=updated["id"],
        actor_user_id=admin_id,
    )
    assert result == {"ok": True}
    deleted_audit = await _audit_log(db, "admin.governance.exec_policy.deleted", updated["id"])
    assert deleted_audit is not None
    assert deleted_audit.resource_type == "exec_policy_config"
    assert deleted_audit.details["operation"] == "delete_exec_policy_payload"
    assert deleted_audit.details["after"] == {}


@pytest.mark.asyncio
async def test_stored_secret_admin_metadata_and_rotation_record_secret_safe_audit_logs(db):
    admin_id = await _admin_user_id(db)
    initial_secret = "initial-governance-secret-value"
    rotated_secret = "rotated-governance-secret-value"
    secret = await set_secret_value(
        db,
        tool_name="governance",
        field_name="api_token",
        project_id=None,
        value=initial_secret,
        expires_at=utc_now() + timedelta(days=7),
    )
    await db.commit()

    updated = await admin_secret_service.update_stored_secret_for_admin(
        db,
        secret_id=secret.id,
        payload={"expires_at": (utc_now() + timedelta(days=14)).isoformat()},
        actor_user_id=admin_id,
    )
    assert updated["id"] == secret.id
    metadata_audit = await _audit_log(db, "admin.security.stored_secret.metadata_updated", secret.id)
    assert metadata_audit is not None
    assert metadata_audit.user_id == admin_id
    assert metadata_audit.resource_type == "stored_secret"
    assert "expires_at" in metadata_audit.details["changed_keys"]
    assert metadata_audit.details["operation"] == "update_stored_secret_for_admin"
    _assert_no_governance_secret_values(metadata_audit.details, initial_secret, rotated_secret)

    rotated = await admin_secret_service.rotate_stored_secret_for_admin(
        db,
        secret_id=secret.id,
        rotated_by=admin_id,
        payload={
            "value": rotated_secret,
            "expires_at": (utc_now() + timedelta(days=45)).isoformat(),
            "note": "manual governance rotation",
        },
        actor_user_id=admin_id,
    )
    assert rotated["id"] == secret.id
    rotation_audit = await _audit_log(db, "admin.security.stored_secret.rotated", secret.id)
    assert rotation_audit is not None
    assert rotation_audit.user_id == admin_id
    assert rotation_audit.resource_type == "stored_secret"
    assert rotation_audit.details["operation"] == "rotate_stored_secret_for_admin"
    assert "value" in rotation_audit.details["payload_keys"]
    assert rotation_audit.details["note_present"] is True
    _assert_no_governance_secret_values(rotation_audit.details, initial_secret, rotated_secret)


@pytest.mark.asyncio
async def test_feature_flag_admin_mutations_record_audit_logs(db):
    admin_id = await _admin_user_id(db)
    key = f"governance-audit-{uuid.uuid4().hex[:8]}"
    saved = await upsert_feature_flag(
        db,
        payload={
            "key": key,
            "description": "Governance audit flag",
            "enabled": True,
            "rollout_percentage": 50,
            "allowed_projects": ["demo"],
            "allowed_roles": ["Admin"],
        },
        actor_user_id=admin_id,
    )
    assert saved["key"] == key
    saved_audit = await _audit_log(db, "admin.security.feature_flag.saved", key)
    assert saved_audit is not None
    assert saved_audit.user_id == admin_id
    assert saved_audit.resource_type == "feature_flag"
    assert set(saved_audit.details["changed_keys"]) >= {"key", "enabled", "rollout_percentage"}
    assert saved_audit.details["operation"] == "upsert_feature_flag"

    deleted = await delete_feature_flag(db, key=key, actor_user_id=admin_id)
    assert deleted == {"status": "deleted", "key": key}
    deleted_audit = await _audit_log(db, "admin.security.feature_flag.deleted", key)
    assert deleted_audit is not None
    assert deleted_audit.user_id == admin_id
    assert deleted_audit.resource_type == "feature_flag"
    assert deleted_audit.details["operation"] == "delete_feature_flag"
    assert deleted_audit.details["after"] == {}
