"""Runtime resolution with tool requirements and costs, explicit targets with fallbacks and use case tags."""

import uuid

import pytest

from app.models import LLMModel, LLMProvider
from app.services.control_plane_service import resolve_control_plane_runtimes, upsert_runtime_target
from tests.control_plane_support import _clear_runtime_targets, _set_provider_api_key_secret


@pytest.mark.asyncio
async def test_resolve_control_plane_runtimes_filters_tool_requirement_and_exposes_cost(db):
    await _clear_runtime_targets(db)

    text_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Text Only Provider",
        default_model_id="vendor/text-only",
        is_global=True,
        is_active=True,
    )
    tool_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Tool Provider",
        default_model_id="vendor/tool-model",
        is_global=True,
        is_active=True,
    )
    db.add_all([text_provider, tool_provider])
    await db.flush()
    await _set_provider_api_key_secret(db, text_provider, "key-text")
    await _set_provider_api_key_secret(db, tool_provider, "key-tools")
    await upsert_runtime_target(
        db,
        provider=text_provider,
        model_id="vendor/text-only",
        make_primary=True,
        is_active=True,
    )
    await upsert_runtime_target(
        db,
        provider=tool_provider,
        model_id="vendor/tool-model",
        make_primary=False,
        is_active=True,
    )
    db.add_all(
        [
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=text_provider.id,
                model_id="vendor/text-only",
                display_name="Text Only",
                supports_tools=False,
                pricing_input=0.10,
                pricing_output=0.20,
                is_active=True,
            ),
            LLMModel(
                id=str(uuid.uuid4()),
                provider_id=tool_provider.id,
                model_id="vendor/tool-model",
                display_name="Tool Model",
                supports_tools=True,
                pricing_input=0.30,
                pricing_output=0.40,
                is_active=True,
            ),
        ]
    )
    await db.commit()

    selected = await resolve_control_plane_runtimes(db, requires_tools=True)
    assert [runtime["model"] for runtime in selected] == ["vendor/tool-model"]
    assert selected[0]["supports_tools"] is True
    assert selected[0]["pricing_input"] == 0.30
    assert selected[0]["pricing_output"] == 0.40
    assert selected[0]["selection_decision"]["inputs"]["cost"]["pricing_state"] == "configured"
    assert selected[0]["selection_decision"]["inputs"]["cost"]["budget_state"] == "not_configured"

    with_skipped = await resolve_control_plane_runtimes(db, requires_tools=True, include_skipped=True)
    assert [runtime["selection_status"] for runtime in with_skipped] == ["skipped", "selected"]
    assert with_skipped[0]["selection_reason"] == "tools_not_supported"
    assert with_skipped[0]["selection_decision"]["inputs"]["requires_tools"] is True


@pytest.mark.asyncio
async def test_resolve_control_plane_runtimes_with_explicit_target_keeps_fallbacks(db):
    await _clear_runtime_targets(db)

    primary_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Enterprise",
        auth_mode="auth_session",
        default_model_id="gpt-5.3-codex",
        is_global=True,
        is_active=True,
    )
    fallback_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Enterprise",
        auth_mode="auth_session",
        default_model_id="gpt-4o",
        is_global=True,
        is_active=True,
    )
    db.add(primary_provider)
    db.add(fallback_provider)
    await db.flush()

    primary_target = await upsert_runtime_target(
        db,
        provider=primary_provider,
        model_id="gpt-5.3-codex",
        make_primary=True,
        is_active=True,
    )
    primary_target.use_case_tags = ["complex_code", "edit"]
    await upsert_runtime_target(
        db,
        provider=fallback_provider,
        model_id="gpt-4o",
        make_primary=False,
        is_active=True,
    )
    await db.commit()

    async def fake_build_provider_client_kwargs_async(_db, provider):
        return {
            "provider_name": provider.name,
            "driver": "copilot_api",
            "runtime_kind": "api",
            "provider_family": "copilot",
            "copilot_token": "test-token",
        }

    from app.services import control_plane_service as control_plane_service_module

    original = control_plane_service_module.build_provider_client_kwargs_async
    control_plane_service_module.build_provider_client_kwargs_async = fake_build_provider_client_kwargs_async
    try:
        runtimes = await resolve_control_plane_runtimes(db, runtime_target_id=primary_target.id)
    finally:
        control_plane_service_module.build_provider_client_kwargs_async = original

    assert len(runtimes) == 2
    assert runtimes[0]["target_id"] == primary_target.id
    assert runtimes[0]["model"] == "gpt-5.3-codex"
    # A runtime's role tags are its Task models, not admin-typed target tags.
    assert runtimes[0]["use_case_tags"] == []
    assert runtimes[1]["model"] == "gpt-4o"
