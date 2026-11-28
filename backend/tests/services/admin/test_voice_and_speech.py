"""Voice & speech: every offered field round-trips; Teams calling resolves with the Workspace."""

from __future__ import annotations

import pytest

from app.services.admin.panel._admin_misc_speech import get_tts_masked_config, save_tts_masked_config
from app.services.teams_calling import audio_pipeline


@pytest.mark.asyncio
async def test_a_tts_key_round_trips_masked():
    stored: dict[tuple[str, str], str] = {}

    async def set_value(_db, *, tool_name, field_name, project_id, value):
        stored[(tool_name, field_name)] = value

    async def get_value(_db, *, tool_name, field_name, project_id, purpose):
        return stored.get((tool_name, field_name))

    class Db:
        async def commit(self):
            return None

    await save_tts_masked_config(Db(), payload={"elevenlabs_api_key": "k-value", "openai_api_key": "••••••••"},
                                 set_secret_value_func=set_value)
    masked = await get_tts_masked_config(Db(), get_secret_value_func=get_value)

    assert stored == {("tts", "elevenlabs_api_key"): "k-value"}  # a masked value is never written back
    assert masked["elevenlabs_api_key"] == "••••••••" and masked["openai_api_key"] == ""


@pytest.mark.asyncio
async def test_teams_calling_speech_uses_the_workspace_voice_settings(monkeypatch):
    seen = []

    async def fake_provider(_db, provider_name=None, project_id=None):
        seen.append(project_id)
        return None

    monkeypatch.setattr(audio_pipeline, "get_tts_provider", fake_provider)
    assert await audio_pipeline.tts_to_pcm("Hello", object(), project_id="ws-1") is None
    assert seen == ["ws-1"]
