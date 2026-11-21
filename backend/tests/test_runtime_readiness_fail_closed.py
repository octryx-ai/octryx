"""Configured-but-unready runtimes fail closed instead of using the env fallback."""

import uuid

import pytest
from sqlalchemy import inspect

from app.models import LLMProvider
from app.services.control_plane_service import (
    resolve_control_plane_runtime,
    resolve_control_plane_runtimes,
    upsert_runtime_target,
)
from app.services.runtime_options import list_chat_runtime_options
from app.services.session.runtime_readiness_gate import evaluate_runtime_readiness
from tests.runtime_readiness_fail_closed_support import _bedrock_target, _clear_runtime_targets


@pytest.mark.asyncio
async def test_zero_runtime_targets_keep_environment_bootstrap_fallback(db, monkeypatch):
    await _clear_runtime_targets(db)
    await db.commit()

    async def _no_defaults(_db, _config):
        return None

    # Simulate an installation where no default target can be seeded.
    monkeypatch.setattr("app.services.control_plane_service.ensure_default_runtime_target", _no_defaults)

    runtimes = await resolve_control_plane_runtimes(db)

    assert len(runtimes) == 1
    assert runtimes[0]["target_id"] is None
    assert runtimes[0]["selection_reason"] == "environment_fallback"


@pytest.mark.asyncio
async def test_explicit_unready_target_returns_no_runtime_instead_of_environment_fallback(db):
    await _clear_runtime_targets(db)
    _provider, target = await _bedrock_target(db, credentials_configured=False)

    runtimes = await resolve_control_plane_runtimes(db, runtime_target_id=target.id)

    assert runtimes == []
    with pytest.raises(RuntimeError, match="No configured runtime target is ready"):
        await resolve_control_plane_runtime(db)

    with_skipped = await resolve_control_plane_runtimes(db, runtime_target_id=target.id, include_skipped=True)
    assert [item["target_id"] for item in with_skipped] == [target.id]
    assert with_skipped[0]["selection_status"] == "skipped"
    assert with_skipped[0]["selection_reason"] == "aws_credentials_not_configured"


@pytest.mark.asyncio
async def test_all_configured_targets_unready_return_empty_list(db):
    await _clear_runtime_targets(db)
    await _bedrock_target(db, credentials_configured=False)
    unready_key_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Keyless OpenRouter",
        auth_mode="api_key",
        default_model_id="vendor/model",
        is_global=True,
        is_active=True,
    )
    db.add(unready_key_provider)
    await db.flush()
    await upsert_runtime_target(
        db, provider=unready_key_provider, model_id="vendor/model", make_primary=False, is_active=True
    )
    await db.commit()

    assert await resolve_control_plane_runtimes(db) == []
    reasons = {item["selection_reason"] for item in await resolve_control_plane_runtimes(db, include_skipped=True)}
    assert reasons == {"aws_credentials_not_configured", "api_key_not_configured"}


@pytest.mark.asyncio
async def test_inactive_configured_targets_do_not_reenable_environment_fallback(db):
    await _clear_runtime_targets(db)
    _provider, target = await _bedrock_target(db, credentials_configured=True)
    target.is_active = False
    await db.commit()

    assert await resolve_control_plane_runtimes(db) == []


@pytest.mark.asyncio
async def test_configured_ready_bedrock_target_is_selected(db):
    await _clear_runtime_targets(db)
    provider, target = await _bedrock_target(db, credentials_configured=True)

    runtimes = await resolve_control_plane_runtimes(db, runtime_target_id=target.id)

    assert [item["target_id"] for item in runtimes] == [target.id]
    assert runtimes[0]["provider_id"] == provider.id
    assert runtimes[0]["selection_status"] == "selected"


def test_readiness_gate_blocks_empty_runtime_set_with_secret_free_reasons():
    skipped_payload = {
        "target_id": "target-1",
        "provider_id": "provider-1",
        "provider_name": "bedrock",
        "model": "anthropic.claude-sonnet-4-6",
        "api_key": "sk-secret-value",
        "aws_secret_access_key": "aws-secret-value",
        "config_json": {"token": "raw-config-secret"},
        "selection_status": "skipped",
        "selection_reason": "aws_credentials_not_configured",
        "readiness_status": "needs_configuration",
        "readiness_reason": "aws_credentials_not_configured",
        "selection_decision": {"skipped_reasons": ["aws_credentials_not_configured"]},
    }
    selected_payload = {**skipped_payload, "target_id": "target-2", "selection_status": "selected"}

    decision = evaluate_runtime_readiness([], skipped_runtimes=[skipped_payload, selected_payload])

    assert decision.allowed is False
    assert decision.status == "needs_configuration"
    assert [item["target_id"] for item in decision.skipped_targets] == ["target-1"]
    assert "aws_credentials_not_configured" in decision.user_message
    serialized = repr(decision.to_metadata()) + decision.user_message
    for secret in ("sk-secret-value", "aws-secret-value", "raw-config-secret"):
        assert secret not in serialized
    assert evaluate_runtime_readiness([{"target_id": "ready"}]).allowed is True


@pytest.mark.asyncio
async def test_chat_runtime_options_disable_unready_targets_and_skip_them_in_automatic_label(db):
    await _clear_runtime_targets(db)
    ready_provider, ready_target = await _bedrock_target(
        db, credentials_configured=True, model_id="anthropic.ready-model"
    )
    unready_provider, unready_target = await _bedrock_target(
        db, credentials_configured=False, model_id="anthropic.unready-model"
    )
    # The unready target has top priority; Auto must still name the ready one.
    assert unready_target.priority < ready_target.priority

    options = {option["value"]: option for option in await list_chat_runtime_options(db)}

    assert options[unready_target.id]["disabled"] is True
    assert "aws_credentials_not_configured" in options[unready_target.id]["disabled_reason"]
    assert "disabled" not in options[ready_target.id]
    # The label names the model by its catalog display name, not provider / raw id.
    assert options[""]["label"] == "Automatic · anthropic.ready-model"
    assert unready_provider.display_name not in options[""]["label"]


@pytest.mark.asyncio
async def test_chat_runtime_options_eager_load_credential_state_for_identity_mapped_provider(db):
    await _clear_runtime_targets(db)
    provider, target = await _bedrock_target(db, credentials_configured=True)
    provider_id, target_id = provider.id, target.id
    db.expire_all()
    # Load the provider into the identity map without its oauth_config relationship.
    loaded = await db.get(LLMProvider, provider_id)
    assert loaded is not None
    assert "oauth_config" in inspect(loaded).unloaded

    options = {option["value"]: option for option in await list_chat_runtime_options(db)}

    assert "disabled" not in options[target_id]
