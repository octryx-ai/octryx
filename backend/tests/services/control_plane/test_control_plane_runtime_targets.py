"""Resolving the first prioritized runtime target and skipping inactive models or unready providers with a reason."""

import uuid

import pytest

from app.models import LLMModel
from app.services.control_plane.selection_policy import SELECTION_POLICY_VERSION
from app.services.control_plane_service import (
    resolve_control_plane_runtime,
    resolve_control_plane_runtimes,
    upsert_runtime_target,
)
from tests.control_plane_support import _clear_runtime_targets, _set_provider_api_key_secret
from tests.model_gateway.conftest import gateway_provider


@pytest.mark.asyncio
async def test_resolve_control_plane_runtime_uses_first_prioritized_target(db):
    await _clear_runtime_targets(db)

    primary_provider = gateway_provider(
        display_name="Primary OpenRouter",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    fallback_provider = gateway_provider(
        display_name="Fallback OpenRouter",
        default_model_id="nvidia/nemotron-3-super-120b-a12b:free",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    db.add(primary_provider)
    db.add(fallback_provider)
    await db.flush()
    await _set_provider_api_key_secret(db, primary_provider, "key-primary")
    await _set_provider_api_key_secret(db, fallback_provider, "key-fallback")

    await upsert_runtime_target(
        db,
        provider=fallback_provider,
        model_id="nvidia/nemotron-3-super-120b-a12b:free",
        make_primary=False,
        is_active=True,
    )
    await upsert_runtime_target(
        db,
        provider=primary_provider,
        model_id="stepfun/step-3.5-flash:free",
        make_primary=True,
        is_active=True,
    )
    await db.commit()

    runtimes = await resolve_control_plane_runtimes(db)
    assert len(runtimes) == 2
    assert runtimes[0]["provider_name"] == "litellm_gateway"
    assert runtimes[0]["api_key"] == "key-primary"
    assert runtimes[0]["model"] == "stepfun/step-3.5-flash:free"
    assert runtimes[0]["selection_policy"] == SELECTION_POLICY_VERSION
    assert runtimes[0]["selection_status"] == "selected"
    assert runtimes[0]["selection_reason"] == "selected_by_priority"
    assert runtimes[0]["selection_decision"]["inputs"]["priority"] == 1
    assert runtimes[1]["api_key"] == "key-fallback"

    runtime = await resolve_control_plane_runtime(db)
    assert runtime["api_key"] == "key-primary"


@pytest.mark.asyncio
async def test_resolve_control_plane_runtimes_skips_inactive_models_with_explicit_reason(db):
    await _clear_runtime_targets(db)

    inactive_provider = gateway_provider(
        display_name="Inactive Model Provider",
        default_model_id="vendor/inactive-model",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    active_provider = gateway_provider(
        display_name="Active Model Provider",
        default_model_id="vendor/active-model",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    db.add_all([inactive_provider, active_provider])
    await db.flush()
    await _set_provider_api_key_secret(db, inactive_provider, "key-inactive-model")
    await _set_provider_api_key_secret(db, active_provider, "key-active-model")
    await upsert_runtime_target(
        db,
        provider=inactive_provider,
        model_id="vendor/inactive-model",
        make_primary=True,
        is_active=True,
    )
    await upsert_runtime_target(
        db,
        provider=active_provider,
        model_id="vendor/active-model",
        make_primary=False,
        is_active=True,
    )
    db.add_all(
        [
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=inactive_provider.id,
                model_id="vendor/inactive-model",
                display_name="Inactive Model",
                supports_tools=True,
                is_active=False,
            ),
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=active_provider.id,
                model_id="vendor/active-model",
                display_name="Active Model",
                supports_tools=True,
                is_active=True,
            ),
        ]
    )
    await db.commit()

    selected = await resolve_control_plane_runtimes(db)
    assert [runtime["model"] for runtime in selected] == ["vendor/active-model"]

    with_skipped = await resolve_control_plane_runtimes(db, include_skipped=True)
    assert [runtime["selection_status"] for runtime in with_skipped] == ["skipped", "selected"]
    assert with_skipped[0]["selection_reason"] == "model_inactive"
    assert with_skipped[0]["selection_decision"]["skipped_reasons"] == ["model_inactive"]


@pytest.mark.asyncio
async def test_resolve_control_plane_runtimes_skips_unready_provider_with_readiness_reason(db):
    await _clear_runtime_targets(db)

    unready_provider = gateway_provider(
        display_name="Unready Provider",
        default_model_id="vendor/unready-model",
        health_status="error",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    ready_provider = gateway_provider(
        display_name="Ready Provider",
        default_model_id="vendor/ready-model",
        health_status="ok",
        is_global=True,
        is_active=True,
        api_key_secret_ref=None,
    )
    db.add_all([unready_provider, ready_provider])
    await db.flush()
    await _set_provider_api_key_secret(db, unready_provider, "key-unready-provider")
    await _set_provider_api_key_secret(db, ready_provider, "key-ready-provider")
    await upsert_runtime_target(
        db,
        provider=unready_provider,
        model_id="vendor/unready-model",
        make_primary=True,
        is_active=True,
    )
    await upsert_runtime_target(
        db,
        provider=ready_provider,
        model_id="vendor/ready-model",
        make_primary=False,
        is_active=True,
    )
    await db.commit()

    selected = await resolve_control_plane_runtimes(db)
    assert [runtime["model"] for runtime in selected] == ["vendor/ready-model"]
    assert selected[0]["readiness_status"] == "ready"
    assert selected[0]["readiness_reason"] == "health_check_ok"

    with_skipped = await resolve_control_plane_runtimes(db, include_skipped=True)
    assert [runtime["selection_status"] for runtime in with_skipped] == ["skipped", "selected"]
    assert with_skipped[0]["selection_reason"] == "health_error"
    assert with_skipped[0]["readiness_status"] == "unavailable"
    assert with_skipped[0]["selection_decision"]["inputs"]["readiness"]["runtime_attempt_allowed"] is False
