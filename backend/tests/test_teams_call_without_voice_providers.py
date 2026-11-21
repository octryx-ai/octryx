"""A Teams call degrades cleanly when no speech provider is configured.

The release ships no bundled speech services: speech-to-text and text-to-speech come from a configured
provider (a self-hosted OpenAI-compatible Whisper, AWS, Azure, OpenAI, ElevenLabs, Polly). Without one, a
call turn neither raises nor reaches the agent: the call keeps recording, and no audio is played.
"""

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
