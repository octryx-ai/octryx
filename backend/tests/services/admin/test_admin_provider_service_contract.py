from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import LLMProvider
from app.services.admin.provider import admin_provider_service
from tests.admin_provider_service_contract_support import _assert_provider_audit_has_no_secret_values, _audit_log
from tests.model_gateway.conftest import BASE_URL, gateway_config


@pytest.mark.asyncio
async def test_create_provider_stores_panel_api_key_as_secret_ref(db):
    captured: list[tuple[str, str, str]] = []

    async def fake_set_secret_value(_db, *, tool_name, field_name, project_id, value):
        captured.append((tool_name, field_name, value))
        return type("SecretRef", (), {"id": "secret-id-create"})()

    created = await admin_provider_service.create_provider(
        db,
        payload={
            "driver": "litellm_gateway",
            "display_name": "Gateway",
            "endpoint_url": BASE_URL,
            "api_key": "sk-panel-create",
            "config_json": {**gateway_config(), "env": {"OPENAI_API_KEY": "sk-config-audit", "SAFE_FLAG": "1"}},
        },
        serialize_provider=lambda provider, model_count, active_count: {"id": provider.id},
        set_secret_value_func=fake_set_secret_value,
        actor_user_id="provider-audit-admin",
    )

    provider = (await db.execute(select(LLMProvider).where(LLMProvider.id == created["id"]))).scalar_one()
    assert not hasattr(provider, "api_key")
    assert provider.api_key_secret_ref == "secret-id-create"
    assert captured == [(f"control_plane_provider:{provider.id}", "api_key", "sk-panel-create")]
    audit = await _audit_log(db, "admin.provider.created", provider.id)
    assert audit.user_id == "provider-audit-admin"
    assert audit.resource_type == "provider_config"
    assert set(audit.details["changed_keys"]) >= {"id", "name", "display_name"}
    assert audit.details["operation"] == "create_provider"
    assert "api_key" not in audit.details["after"]
    assert audit.details["after"]["api_key_secret_ref"] == "[redacted]"
    assert audit.details["after"]["config_json"]["env"]["OPENAI_API_KEY"] == "[redacted]"
    assert audit.details["after"]["config_json"]["env"]["SAFE_FLAG"] == "1"
    assert "api_key" in audit.details["payload_keys"]
    _assert_provider_audit_has_no_secret_values(audit.details)


@pytest.mark.asyncio
async def test_update_provider_stores_panel_api_key_as_secret_ref(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="litellm_gateway",
        driver="litellm_gateway",
        display_name="Gateway",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    captured: list[tuple[str, str, str]] = []

    async def fake_set_secret_value(_db, *, tool_name, field_name, project_id, value):
        captured.append((tool_name, field_name, value))
        return type("SecretRef", (), {"id": "secret-id-update"})()

    await admin_provider_service.update_provider(
        db,
        provider_id=provider.id,
        payload={"api_key": "sk-panel-update", "display_name": "Gateway Updated"},
        serialize_provider=lambda current, model_count, active_count: {"id": current.id},
        set_secret_value_func=fake_set_secret_value,
        actor_user_id="provider-audit-admin",
    )

    refreshed = await db.get(LLMProvider, provider.id)
    assert refreshed is not None
    assert not hasattr(refreshed, "api_key")
    assert refreshed.api_key_secret_ref == "secret-id-update"
    assert captured == [(f"control_plane_provider:{provider.id}", "api_key", "sk-panel-update")]
    audit = await _audit_log(db, "admin.provider.updated", provider.id)
    assert audit.user_id == "provider-audit-admin"
    assert audit.resource_type == "provider_config"
    assert "display_name" in audit.details["changed_keys"]
    assert audit.details["operation"] == "update_provider"
    assert "api_key" in audit.details["payload_keys"]
    assert "api_key" not in audit.details["after"]
    assert audit.details["after"]["api_key_secret_ref"] == "[redacted]"
    _assert_provider_audit_has_no_secret_values(audit.details)


@pytest.mark.asyncio
async def test_delete_provider_records_secret_safe_audit_log(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="litellm_gateway",
        driver="litellm_gateway",
        display_name="Delete Provider",
        api_key_secret_ref="secret-id-delete",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    result = await admin_provider_service.delete_provider(
        db,
        provider_id=provider.id,
        actor_user_id="provider-audit-admin",
    )

    assert result == {"status": "deleted"}
    audit = await _audit_log(db, "admin.provider.deleted", provider.id)
    assert audit.user_id == "provider-audit-admin"
    assert audit.resource_type == "provider_config"
    assert audit.details["operation"] == "delete_provider"
    assert "api_key" not in audit.details["before"]
    assert audit.details["before"]["api_key_secret_ref"] == "[redacted]"
    assert audit.details["after"] == {}
    _assert_provider_audit_has_no_secret_values(audit.details)
