"""Falling back to the next runtime when the primary fails or returns nothing, and building provider client kwargs."""

import uuid

import pytest
from sqlalchemy import select

from app.models import LLMProvider, Project
from app.services.control_plane_service import (
    build_provider_client_kwargs,
    build_provider_client_kwargs_async,
    upsert_runtime_target,
)
from app.services.secret import set_secret_value
from tests.control_plane_support import _clear_runtime_targets, _set_provider_api_key_secret


@pytest.mark.asyncio
async def test_send_message_uses_fallback_runtime_when_primary_fails(client, auth_headers, db, monkeypatch):
    await _clear_runtime_targets(db)

    primary_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Primary OpenRouter",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
    )
    fallback_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Fallback OpenRouter",
        default_model_id="nvidia/nemotron-3-super-120b-a12b:free",
        is_global=True,
        is_active=True,
    )
    db.add(primary_provider)
    db.add(fallback_provider)
    await db.flush()
    await _set_provider_api_key_secret(db, primary_provider, "primary-key")
    await _set_provider_api_key_secret(db, fallback_provider, "fallback-key")

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

    captured = {"attempts": []}

    class FakeProvider:
        def __init__(self, api_key):
            self.api_key = api_key

        async def chat(self, messages, model, tools=None, temperature=0, max_tokens=4096, **_options):
            captured["attempts"].append((self.api_key, model))
            if self.api_key == "primary-key":
                raise RuntimeError("rate limited")
            return {
                # A substantive answer: a bare "OK" on a turn that offers tools gets one reminder.
                "content": "The fallback runtime answered the test message.",
                "tool_calls": None,
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "model": model,
            }

        async def close(self):
            return None

    def fake_get_provider(provider_name=None, api_key=None, region=None, role_arn=None, copilot_token=None):
        return FakeProvider(api_key or copilot_token)

    monkeypatch.setattr("app.agent.engine.get_provider", fake_get_provider)

    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis", "project_id": demo_project.id},
        headers=auth_headers,
    )
    session_id = session_resp.json()["id"]

    message_resp = await client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "test"},
        headers=auth_headers,
    )
    assert message_resp.status_code == 200
    # A transient primary failure ("rate limited") gets one same-runtime retry
    # before the chain falls back.
    assert captured["attempts"] == [
        ("primary-key", "stepfun/step-3.5-flash:free"),
        ("primary-key", "stepfun/step-3.5-flash:free"),
        ("fallback-key", "nvidia/nemotron-3-super-120b-a12b:free"),
    ]


@pytest.mark.asyncio
async def test_send_message_uses_fallback_runtime_when_primary_returns_empty_output(
    client,
    auth_headers,
    db,
    monkeypatch,
):
    await _clear_runtime_targets(db)

    primary_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Primary OpenRouter",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
    )
    fallback_provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Fallback OpenRouter",
        default_model_id="nvidia/nemotron-3-super-120b-a12b:free",
        is_global=True,
        is_active=True,
    )
    db.add(primary_provider)
    db.add(fallback_provider)
    await db.flush()
    await _set_provider_api_key_secret(db, primary_provider, "primary-key")
    await _set_provider_api_key_secret(db, fallback_provider, "fallback-key")

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

    captured = {"attempts": []}

    class FakeProvider:
        def __init__(self, api_key):
            self.api_key = api_key

        async def chat(self, messages, model, tools=None, temperature=0, max_tokens=4096, **_options):
            captured["attempts"].append((self.api_key, model, max_tokens))
            if self.api_key == "primary-key":
                return {
                    "content": "",
                    "tool_calls": None,
                    "usage": {"prompt_tokens": 1, "completion_tokens": max_tokens},
                    "model": model,
                }
            return {
                "content": "Recovered on fallback",
                "tool_calls": None,
                "usage": {"prompt_tokens": 1, "completion_tokens": 5},
                "model": model,
            }

        async def close(self):
            return None

    def fake_get_provider(provider_name=None, api_key=None, region=None, role_arn=None, copilot_token=None):
        return FakeProvider(api_key or copilot_token)

    monkeypatch.setattr("app.agent.engine.get_provider", fake_get_provider)

    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    session_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis", "project_id": demo_project.id},
        headers=auth_headers,
    )
    session_id = session_resp.json()["id"]

    message_resp = await client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "test"},
        headers=auth_headers,
    )
    assert message_resp.status_code == 200
    assert captured["attempts"][0][:2] == ("primary-key", "stepfun/step-3.5-flash:free")
    assert captured["attempts"][1][:2] == ("fallback-key", "nvidia/nemotron-3-super-120b-a12b:free")


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_uses_copilot_token(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot UI",
        default_model_id="gpt-4o",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await _set_provider_api_key_secret(db, provider, "copilot-token")
    await db.commit()

    kwargs = await build_provider_client_kwargs_async(db, provider)
    assert kwargs["provider_name"] == "copilot"
    assert kwargs["api_key"] is None
    assert kwargs["copilot_token"] == "copilot-token"
    assert kwargs["auth_mode"] == "api_key"


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_uses_encrypted_secret_for_openrouter(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="Encrypted Route",
        default_model_id="stepfun/step-3.5-flash:free",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.flush()

    save_tool_name = f"control_plane_provider:{provider.id}"
    secret_entry = await set_secret_value(
        db,
        tool_name=save_tool_name,
        field_name="api_key",
        project_id=None,
        value="encrypted-openrouter-key",
    )
    provider.api_key_secret_ref = secret_entry.id
    await db.commit()

    public_kwargs = build_provider_client_kwargs(provider)
    assert public_kwargs["api_key"] is None
    assert "encrypted-openrouter-key" not in str(public_kwargs)

    kwargs = await build_provider_client_kwargs_async(db, provider)
    assert kwargs["provider_name"] == "openrouter"
    assert kwargs["api_key"] == "encrypted-openrouter-key"


@pytest.mark.asyncio
async def test_build_provider_client_kwargs_async_uses_copilot_auth_session_without_token(db):
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="copilot",
        driver="copilot_api",
        display_name="Copilot Session",
        auth_mode="auth_session",
        default_model_id="gpt-4o",
        is_global=True,
        is_active=True,
    )
    db.add(provider)
    await db.commit()

    kwargs = await build_provider_client_kwargs_async(db, provider)
    assert kwargs["provider_name"] == "copilot"
    assert kwargs["auth_mode"] == "auth_session"
    assert kwargs["copilot_token"] is None
