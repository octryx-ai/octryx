import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, Project
from app.services.secret import set_secret_value
from app.services.tts import (
    OpenAITTSProvider,
    TTSConfig,
    TTSProviderConfig,
    get_tts_provider,
    has_active_tts_provider,
    list_tts_providers,
    load_tts_config,
    resolve_tts_provider,
    save_tts_config,
)
from app.services.tts import service as tts_service


class FakeTTSAsyncClient:
    requests: list[dict] = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, json=None, data=None):
        self.requests.append(
            {
                "url": url,
                "headers": headers or {},
                "json": json,
                "data": data,
            }
        )
        return httpx.Response(
            200,
            content=b"wav",
            headers={"content-type": "audio/wav"},
            request=httpx.Request("POST", url),
        )


def _failing_elevenlabs(monkeypatch):
    """ElevenLabs fails to build (as a misconfigured provider would), every other provider builds as usual."""
    original = tts_service._build_tts_provider

    async def build(db, provider):
        if provider.provider == "elevenlabs":
            raise ValueError("misconfigured")
        return await original(db, provider)

    monkeypatch.setattr(tts_service, "_build_tts_provider", build)


@pytest.mark.asyncio
async def test_tts_config_round_trip_preserves_provider_settings(db):
    config = TTSConfig(
        enabled=True,
        default_voice="echo",
        default_speed=1.25,
        allow_provider_fallback=False,
        providers=[
            TTSProviderConfig(
                provider="openai",
                enabled=True,
                priority=2,
                config={"model": "tts-1-hd", "base_url": "https://example.test"},
            )
        ],
    )

    await save_tts_config(db, config)
    loaded = await load_tts_config(db)

    assert loaded.enabled is True
    assert loaded.default_voice == "echo"
    assert loaded.default_speed == 1.25
    assert loaded.allow_provider_fallback is False
    assert len(loaded.providers) == 1
    assert loaded.providers[0].provider == "openai"
    assert loaded.providers[0].config["model"] == "tts-1-hd"


@pytest.mark.asyncio
async def test_get_and_list_tts_provider_reflects_saved_config_and_secret(db):
    await set_secret_value(
        db,
        tool_name="tts",
        field_name="openai_api_key",
        project_id=None,
        value="test-openai-key",
    )
    await db.commit()
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            providers=[TTSProviderConfig(provider="openai", enabled=True, priority=1, config={})],
        ),
    )

    provider = await get_tts_provider(db)
    providers = await list_tts_providers(db)

    assert isinstance(provider, OpenAITTSProvider)
    openai_provider = next(item for item in providers if item["id"] == "openai")
    assert openai_provider["enabled"] is True
    assert openai_provider["has_key"] is True


@pytest.mark.asyncio
async def test_tts_provider_listing_only_returns_installed_providers(db):
    providers = await list_tts_providers(db)
    assert providers == []

    await save_tts_config(
        db,
        TTSConfig(
            providers=[
                TTSProviderConfig(provider="browser", enabled=False, priority=1, config={}),
                TTSProviderConfig(provider="openai", enabled=False, priority=2, config={}),
            ],
        ),
    )

    providers = await list_tts_providers(db)
    assert [item["id"] for item in providers] == ["browser", "openai"]
    browser = providers[0]
    assert browser["has_key"] is True
    assert browser["key_required"] is False


@pytest.mark.asyncio
async def test_tts_config_normalizes_to_one_active_provider(db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            allow_provider_fallback=False,
            providers=[
                TTSProviderConfig(provider="browser", enabled=True, priority=2, config={}),
                TTSProviderConfig(provider="openai", enabled=True, priority=1, config={}),
            ],
        ),
    )

    loaded = await load_tts_config(db)
    enabled = [provider.provider for provider in loaded.providers if provider.enabled]
    assert enabled == ["openai"]


@pytest.mark.asyncio
async def test_tts_config_preserves_multiple_active_providers_when_fallback_allowed(db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            allow_provider_fallback=True,
            providers=[
                TTSProviderConfig(provider="browser", enabled=True, priority=2, config={}),
                TTSProviderConfig(provider="openai", enabled=True, priority=1, config={}),
            ],
        ),
    )

    loaded = await load_tts_config(db)
    enabled = [provider.provider for provider in loaded.providers if provider.enabled]
    assert enabled == ["openai", "browser"]


@pytest.mark.asyncio
async def test_resolve_tts_provider_records_fallback_to_next_provider(db, monkeypatch):
    _failing_elevenlabs(monkeypatch)
    await set_secret_value(
        db,
        tool_name="tts",
        field_name="openai_api_key",
        project_id=None,
        value="test-openai-key",
    )
    await db.commit()
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            allow_provider_fallback=True,
            providers=[
                TTSProviderConfig(provider="elevenlabs", enabled=True, priority=1, config={}),
                TTSProviderConfig(provider="openai", enabled=True, priority=2, config={}),
            ],
        ),
    )

    resolution = await resolve_tts_provider(db)

    assert isinstance(resolution.provider, OpenAITTSProvider)
    assert resolution.selected_provider == "openai"
    assert resolution.fallback_allowed is True
    assert resolution.fallback_used is True
    assert [attempt.provider for attempt in resolution.attempts] == ["elevenlabs", "openai"]
    assert [attempt.status for attempt in resolution.attempts] == ["failed", "selected"]


@pytest.mark.asyncio
async def test_resolve_tts_provider_blocks_fallback_when_policy_disabled(db, monkeypatch):
    _failing_elevenlabs(monkeypatch)
    await set_secret_value(
        db,
        tool_name="tts",
        field_name="openai_api_key",
        project_id=None,
        value="test-openai-key",
    )
    await db.commit()
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            allow_provider_fallback=False,
            providers=[
                TTSProviderConfig(provider="elevenlabs", enabled=True, priority=1, config={}),
                TTSProviderConfig(provider="openai", enabled=True, priority=2, config={}),
            ],
        ),
    )

    resolution = await resolve_tts_provider(db)

    assert resolution.provider is None
    assert resolution.selected_provider is None
    assert resolution.fallback_allowed is False
    assert resolution.fallback_used is False
    assert [attempt.status for attempt in resolution.attempts] == ["failed", "blocked"]
    assert resolution.attempts[-1].reason == "fallback_disabled"


@pytest.mark.asyncio
async def test_browser_tts_provider_is_available_without_key(db):
    config = TTSConfig(
        enabled=True,
        providers=[TTSProviderConfig(provider="browser", enabled=True, priority=1, config={})],
    )
    await save_tts_config(db, config)

    loaded = await load_tts_config(db)
    assert await has_active_tts_provider(db, loaded) is True
    assert await get_tts_provider(db) is None


@pytest.mark.asyncio
async def test_project_tts_config_overrides_global_enabled_and_voice(db):
    """Project-level config should override global enabled + default_voice."""
    await set_secret_value(db, tool_name="tts", field_name="openai_api_key", project_id=None, value="test-key")
    await db.commit()
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            default_voice="alloy",
            default_speed=1.0,
            providers=[TTSProviderConfig(provider="openai", enabled=True, priority=1, config={})],
        ),
    )

    # Create a project that disables TTS and overrides voice
    project = Project(id="proj-test-1", name="test-project", config={"tts": {"enabled": False, "default_voice": "echo", "default_speed": 0.9}})
    db.add(project)
    await db.commit()

    # Without project_id → global config
    global_config = await load_tts_config(db)
    assert global_config.enabled is True
    assert global_config.default_voice == "alloy"

    # With project_id → project override wins
    proj_config = await load_tts_config(db, project_id="proj-test-1")
    assert proj_config.enabled is False
    assert proj_config.default_voice == "echo"
    assert proj_config.default_speed == 0.9


@pytest.mark.asyncio
async def test_project_tts_uses_global_provider_credentials(db):
    """Provider credentials come from global secrets regardless of project_id."""
    await set_secret_value(db, tool_name="tts", field_name="openai_api_key", project_id=None, value="global-key")
    await db.commit()
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            providers=[TTSProviderConfig(provider="openai", enabled=True, priority=1, config={})],
        ),
    )

    project = Project(id="proj-test-2", name="test-project-2", config={"tts": {"enabled": True}})
    db.add(project)
    await db.commit()

    # get_tts_provider with project_id should still resolve global credentials
    provider = await get_tts_provider(db, project_id="proj-test-2")
    assert provider is not None
    assert isinstance(provider, OpenAITTSProvider)


@pytest.mark.asyncio
async def test_project_without_tts_config_falls_back_to_global(db):
    """A project with no tts in config falls back to global settings."""
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            default_voice="nova",
            default_speed=1.5,
            providers=[TTSProviderConfig(provider="openai", enabled=True, priority=1, config={})],
        ),
    )

    project = Project(id="proj-no-tts", name="no-tts-project", config={})
    db.add(project)
    await db.commit()

    config = await load_tts_config(db, project_id="proj-no-tts")
    assert config.enabled is True
    assert config.default_voice == "nova"
    assert config.default_speed == 1.5


@pytest.mark.asyncio
async def test_tts_synthesize_redacts_secret_like_provider_errors(client, auth_headers, db, monkeypatch):
    async def fake_synthesize(self, text: str, voice: str, speed: float) -> bytes:
        raise RuntimeError("authorization: Bearer sk-supersecrettoken123 api_key=sk-anothersecret456")

    monkeypatch.setattr(OpenAITTSProvider, "synthesize", fake_synthesize)
    await set_secret_value(
        db,
        tool_name="tts",
        field_name="openai_api_key",
        project_id=None,
        value="test-openai-key",
    )
    await db.commit()
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            providers=[TTSProviderConfig(provider="openai", enabled=True, priority=1, config={})],
        ),
    )

    response = await client.post(
        "/admin/chat/api/v1/tts/synthesize",
        json={"text": "hello", "provider": "openai"},
        headers=auth_headers,
    )

    assert response.status_code == 502
    response_text = response.text
    assert "sk-supersecrettoken123" not in response_text
    assert "sk-anothersecret456" not in response_text
    assert "[redacted]" in response_text
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "speech.tts.synthesis_failed"))
    ).scalar_one()
    assert "sk-supersecrettoken123" not in audit.details["error"]
    assert "sk-anothersecret456" not in audit.details["error"]
    assert "[redacted]" in audit.details["error"]


@pytest.mark.asyncio
async def test_tts_synthesize_rejects_empty_text(client, auth_headers):
    response = await client.post(
        "/admin/chat/api/v1/tts/synthesize",
        json={"text": "   "},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "text must not be empty"


@pytest.mark.asyncio
async def test_tts_synthesize_reports_provider_unavailable_for_browser_backend(client, auth_headers, db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            providers=[TTSProviderConfig(provider="browser", enabled=True, priority=1, config={})],
        ),
    )

    response = await client.post(
        "/admin/chat/api/v1/tts/synthesize",
        json={"text": "hello"},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "No TTS provider configured or available."
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "speech.tts.provider_unavailable"))
    ).scalar_one()
    assert audit.resource_type == "speech_tts"
    assert audit.resource_id == "none"
    assert audit.details["attempts"][0]["provider"] == "browser"
    assert audit.details["attempts"][0]["reason"] == "client_side_only"


@pytest.mark.asyncio
async def test_tts_synthesize_returns_audio_metadata_without_live_provider(client, auth_headers, db, monkeypatch):
    async def fake_synthesize(self, text: str, voice: str, speed: float) -> bytes:
        assert text == "hello"
        assert voice == "alloy"
        assert speed == 1.0
        return b"mp3-bytes"

    monkeypatch.setattr(OpenAITTSProvider, "synthesize", fake_synthesize)
    await set_secret_value(
        db,
        tool_name="tts",
        field_name="openai_api_key",
        project_id=None,
        value="test-openai-key",
    )
    await db.commit()
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            providers=[TTSProviderConfig(provider="openai", enabled=True, priority=1, config={})],
        ),
    )

    response = await client.post(
        "/chat/api/v1/tts/synthesize",
        json={"text": "hello", "provider": "openai"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.content == b"mp3-bytes"
    assert response.headers["content-type"].startswith("audio/mpeg")


@pytest.mark.asyncio
async def test_upsert_tts_provider_adds_and_deactivates_others(db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            providers=[TTSProviderConfig(provider="openai", enabled=True, priority=1, config={})],
        ),
    )

    # browser is available without credentials; enabling it must deactivate openai.
    config = await tts_service.upsert_tts_provider(
        db,
        provider="browser",
        enabled=True,
        priority=2,
        config={},
    )

    enabled = [p.provider for p in config.providers if p.enabled]
    assert enabled == ["browser"]
    assert config.enabled is True


@pytest.mark.asyncio
async def test_upsert_tts_provider_replaces_existing_row(db):
    await tts_service.upsert_tts_provider(db, provider="browser", enabled=False, priority=1, config={"a": 1})
    await tts_service.upsert_tts_provider(db, provider="browser", enabled=False, priority=5, config={"a": 2})

    loaded = await load_tts_config(db)
    browser_rows = [p for p in loaded.providers if p.provider == "browser"]
    assert len(browser_rows) == 1
    assert browser_rows[0].config == {"a": 2}


@pytest.mark.asyncio
async def test_upsert_tts_provider_rejects_unavailable_enabled_provider(db):
    with pytest.raises(ValueError, match="credentials"):
        await tts_service.upsert_tts_provider(db, provider="openai", enabled=True, priority=1, config={})


@pytest.mark.asyncio
async def test_remove_tts_provider_drops_row_and_recomputes_enabled(db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            providers=[TTSProviderConfig(provider="browser", enabled=True, priority=1, config={})],
        ),
    )

    config = await tts_service.remove_tts_provider(db, provider_id="browser")

    assert [p.provider for p in config.providers] == []
    assert config.enabled is False


@pytest.mark.asyncio
async def test_move_tts_provider_swaps_priority(db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            allow_provider_fallback=True,
            providers=[
                TTSProviderConfig(provider="openai", enabled=True, priority=1, config={}),
                TTSProviderConfig(provider="browser", enabled=True, priority=2, config={}),
            ],
        ),
    )

    config = await tts_service.move_tts_provider(db, provider_id="browser", direction="up")
    order = [p.provider for p in sorted(config.providers, key=lambda x: x.priority)]
    assert order == ["browser", "openai"]


@pytest.mark.asyncio
async def test_move_tts_provider_at_edge_is_noop(db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=True,
            allow_provider_fallback=True,
            providers=[
                TTSProviderConfig(provider="openai", enabled=True, priority=1, config={}),
                TTSProviderConfig(provider="browser", enabled=True, priority=2, config={}),
            ],
        ),
    )

    config = await tts_service.move_tts_provider(db, provider_id="openai", direction="up")
    order = [p.provider for p in sorted(config.providers, key=lambda x: x.priority)]
    assert order == ["openai", "browser"]


@pytest.mark.asyncio
async def test_move_tts_provider_missing_raises_keyerror(db):
    await save_tts_config(db, TTSConfig(enabled=False, providers=[]))
    with pytest.raises(KeyError):
        await tts_service.move_tts_provider(db, provider_id="nope", direction="up")


@pytest.mark.asyncio
async def test_serialize_tts_overview_matches_shared_contract(db):
    await save_tts_config(
        db,
        TTSConfig(
            enabled=False,
            default_voice="echo",
            default_speed=1.25,
            allow_provider_fallback=False,
            providers=[TTSProviderConfig(provider="browser", enabled=True, priority=1, config={})],
        ),
    )
    config = await load_tts_config(db)
    resolution = await resolve_tts_provider(db)

    overview = tts_service.serialize_tts_overview(config, resolution, effective_enabled=True)
    assert set(overview) == {
        "enabled",
        "default_voice",
        "default_speed",
        "allow_provider_fallback",
        "fallback_allowed",
        "fallback_used",
        "resolution",
    }
    assert overview["enabled"] is True
    assert overview["default_voice"] == "echo"
    assert overview["default_speed"] == 1.25
    assert overview["allow_provider_fallback"] is False

    rows = tts_service.serialize_tts_provider_rows(config)
    assert rows == [{"provider": "browser", "enabled": True, "priority": 1, "config": {}}]
