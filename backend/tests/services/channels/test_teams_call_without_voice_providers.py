"""A Teams call degrades cleanly when no speech provider is configured."""

from __future__ import annotations

import pytest

from app.services.teams_calling import audio_pipeline, recording_processor


@pytest.mark.asyncio
async def test_a_turn_without_speech_to_text_keeps_the_call_recording_and_never_reaches_the_agent(monkeypatch):
    restarted: list[tuple[str, str]] = []

    async def no_stt(_db):
        return None

    async def restart(call_id, channel_id):
        restarted.append((call_id, channel_id))

    async def agent_response(*_args, **_kwargs):
        raise AssertionError("the agent must not run without a transcript")

    monkeypatch.setattr(recording_processor, "get_stt_service", no_stt)
    monkeypatch.setattr(recording_processor, "restart_recording", restart)
    monkeypatch.setattr(recording_processor, "agent_response", agent_response)

    item = {"call_id": "call-1", "channel_id": "channel-1", "project_id": "", "https_base": ""}
    await recording_processor._process_downloaded_recording(item, b"RIFF....WAVE", db=None)

    assert restarted == [("call-1", "channel-1")]


@pytest.mark.asyncio
async def test_without_text_to_speech_a_reply_has_no_audio(monkeypatch):
    async def no_tts(_db, project_id=None):
        return None

    monkeypatch.setattr(audio_pipeline, "get_tts_provider", no_tts)

    assert await audio_pipeline.tts_to_pcm("hello", db=None) is None


@pytest.mark.asyncio
async def test_a_channel_without_a_thinking_message_still_speaks_the_answer(monkeypatch):
    played: list[str] = []
    restarted: list[str] = []

    class Plugin:
        async def _play_prompt(self, call_id, url):
            played.append(url)

    class Voice:
        async def synthesize(self, text, voice, speed):
            return b"RIFF....WAVE"

    async def tts(_db, project_id=None):
        return Voice()

    async def nothing(*_args, **_kwargs):
        return ""

    async def answer(*_args, **_kwargs):
        return "The order ships today."

    async def restart(call_id, _channel_id):
        restarted.append(call_id)

    monkeypatch.setattr(recording_processor, "get_thinking_message", nothing)
    monkeypatch.setattr(recording_processor, "get_tts_provider", tts)
    monkeypatch.setattr(recording_processor, "agent_response", answer)
    monkeypatch.setattr(recording_processor, "restart_recording", restart)
    monkeypatch.setattr(recording_processor, "estimate_wav_duration", lambda _audio: 0.0)
    monkeypatch.setattr("app.plugins.plugin_manager.get_channel", lambda _channel_id: Plugin())

    item = {"call_id": "call-2", "channel_id": "channel-2", "project_id": "", "https_base": "https://bot.example.com"}
    await recording_processor._answer(item, "Status?", "status", None, db=None)

    assert len(played) == 1 and played[0].startswith("https://bot.example.com/api/v1/teams/calls/call-2/audio/temp/")
    assert restarted == ["call-2"]
