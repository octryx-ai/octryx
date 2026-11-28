"""Adding, updating and syncing provider models record audit logs, and a failed model sync records a structured audit entry."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.agent.runtime.runtime_errors import ProviderRuntimeError
from app.models import LLMProvider
from app.models.runtime.llm_provider import LLMModel
from app.services.admin.provider import _admin_provider_models, admin_provider_service
from tests.admin_provider_service_contract_support import _assert_provider_audit_has_no_secret_values, _audit_log
from tests.model_gateway.conftest import gateway_provider


@pytest.mark.asyncio
async def test_provider_model_add_update_and_sync_record_audit_logs(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="manual",
        display_name="Manual Provider",
        driver="manual",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    added = await _admin_provider_models.add_model(
        db,
        provider_id=provider.id,
        payload={
            "model_id": "manual-model",
            "display_name": "Manual Model",
            "supports_tools": True,
            "pricing_input": "0.10",
            "pricing_output": "0.20",
        },
        actor_user_id="provider-audit-admin",
    )
    created_audit = await _audit_log(db, "admin.provider.model.created", added["id"])
    assert created_audit.user_id == "provider-audit-admin"
    assert created_audit.resource_type == "provider_model"
    assert "model_id" in created_audit.details["changed_keys"]
    assert created_audit.details["operation"] == "add_model"
    assert created_audit.details["provider_id"] == provider.id

    updated = await _admin_provider_models.update_model(
        db,
        provider_id=provider.id,
        model_id=added["id"],
        payload={"display_name": "Manual Model Updated", "supports_tools": False},
        actor_user_id="provider-audit-admin",
    )
    assert updated["display_name"] == "Manual Model Updated"
    updated_audit = await _audit_log(db, "admin.provider.model.updated", added["id"])
    assert updated_audit.user_id == "provider-audit-admin"
    assert updated_audit.resource_type == "provider_model"
    assert set(updated_audit.details["changed_keys"]) >= {"display_name", "supports_tools"}
    assert updated_audit.details["operation"] == "update_model"

    async def fake_build_provider_client_kwargs(_db, _provider):
        raise AssertionError("Manual provider should not invoke external model sync")

    sync_result = await admin_provider_service.sync_provider_models(
        db,
        provider_id=provider.id,
        build_provider_client_kwargs_async_func=fake_build_provider_client_kwargs,
        actor_user_id="provider-audit-admin",
    )
    assert sync_result["status"] == "no_models"
    assert sync_result["sync_state"] == "no_models"
    sync_audit = await _audit_log(db, "admin.provider.models_synced", provider.id)
    assert sync_audit.user_id == "provider-audit-admin"
    assert sync_audit.resource_type == "provider_models"
    assert sync_audit.details["operation"] == "sync_provider_models"
    assert sync_audit.details["sync_state"] == "no_models"
    assert sync_audit.details["provider_supports_model_sync"] is False
    assert sync_audit.details["before"]["model_count"] == 1
    assert sync_audit.details["after"]["model_count"] == 1
    _assert_provider_audit_has_no_secret_values(sync_audit.details)


@pytest.mark.asyncio
async def test_provider_model_sync_failure_records_structured_audit(db, monkeypatch):
    provider = gateway_provider(display_name="Gateway Failure", is_global=True)
    model = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id="cached/model",
        display_name="Cached Model",
        is_active=True,
    )
    db.add_all([provider, model])
    await db.commit()

    async def fake_build_provider_client_kwargs(_db, _provider):
        return {"provider_name": "litellm_gateway", "api_key": "test-key"}

    class FailingClient:
        async def list_models(self):
            raise ProviderRuntimeError(
                "Gateway error (503): bearer token sk-admin-secret failed", error_class="transient",
                status_code=503,
            )

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.providers.get_provider", lambda **_kwargs: FailingClient())

    with pytest.raises(HTTPException) as exc_info:
        await admin_provider_service.sync_provider_models(
            db,
            provider_id=provider.id,
            build_provider_client_kwargs_async_func=fake_build_provider_client_kwargs,
            actor_user_id="provider-audit-admin",
        )

    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert detail["sync_state"] == "stale_cache"
    assert detail["failure_state"] == "provider_unavailable"
    assert detail["cache_state"] == "stale_cache"
    assert "sk-admin-secret" not in str(detail)

    audit = await _audit_log(db, "admin.provider.models_synced", provider.id)
    assert audit.user_id == "provider-audit-admin"
    assert audit.details["sync_state"] == "stale_cache"
    assert audit.details["failure_state"] == "provider_unavailable"
    assert audit.details["cache_state"] == "stale_cache"
    assert audit.details["error_class"] == "ProviderRuntimeError"
    assert "sk-admin-secret" not in str(audit.details)
