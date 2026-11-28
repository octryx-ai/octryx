import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.routes.channels.teams_calling import call_audio_ws
from app.models import ChannelConfig, Project
from app.services.teams_calling.audio import DEFAULT_PCM_FORMAT
from app.services.teams_calling.audio_ws_token import issue_call_audio_token


class FakeAudioWebSocket:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.accepted = False
        self.closed = None
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=None):
        self.closed = (code, reason)

    async def receive_bytes(self):
        if not self._chunks:
            raise WebSocketDisconnect()
        item = self._chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def send_bytes(self, data):
        self.sent.append(data)


async def _project_id(db) -> str:
    project = (await db.execute(Project.__table__.select().limit(1))).first()
    assert project is not None
    return str(project[0])


async def _create_teams_calling_channel(db, *, calling_enabled=True) -> ChannelConfig:
    project_id = await _project_id(db)
    channel = ChannelConfig(
        plugin_id="msteams",
        name="Teams Calling",
        project_id=project_id,
        enabled=True,
        config=json.dumps({"calling_enabled": calling_enabled}),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@pytest.mark.asyncio
async def test_call_audio_ws_closes_before_accept_for_invalid_channel(db):
    websocket = FakeAudioWebSocket([])

    await call_audio_ws(
        call_id="call-1",
        ws=websocket,
        project_id="project-1",
        channel_id="not-an-id",
        token=issue_call_audio_token("call-1", channel_id="not-an-id", project_id="project-1"),
        db=db,
    )

    assert websocket.accepted is False
    assert websocket.closed == (1008, "channel_id must be an integer")


@pytest.mark.asyncio
async def test_call_audio_ws_accepts_valid_channel_and_silence_disconnects_cleanly(db):
    channel = await _create_teams_calling_channel(db)
    silence = b"\x00\x00" * 160
    websocket = FakeAudioWebSocket([silence])

    await call_audio_ws(
        call_id="call-1",
        ws=websocket,
        project_id=str(channel.project_id),
        channel_id=str(channel.id),
        token=issue_call_audio_token("call-1", channel_id=str(channel.id), project_id=str(channel.project_id)),
        db=db,
    )

    assert websocket.accepted is True
    assert websocket.closed is None
    assert websocket.sent == []


@pytest.mark.asyncio
async def test_call_audio_ws_closes_oversized_audio_chunk(db):
    channel = await _create_teams_calling_channel(db)
    oversized_chunk = b"\x00" * (DEFAULT_PCM_FORMAT.bytes_per_second * 5 + 1)
    websocket = FakeAudioWebSocket([oversized_chunk])

    await call_audio_ws(
        call_id="call-1",
        ws=websocket,
        project_id=str(channel.project_id),
        channel_id=str(channel.id),
        token=issue_call_audio_token("call-1", channel_id=str(channel.id), project_id=str(channel.project_id)),
        db=db,
    )

    assert websocket.accepted is True
    assert websocket.closed == (1009, "Audio chunk too large")


@pytest.mark.asyncio
async def test_call_audio_ws_flushes_speech_to_agent_and_tts(db, monkeypatch):
    from app.api.routes.channels import teams_calling

    channel = await _create_teams_calling_channel(db)
    speech = (1000).to_bytes(2, "little", signed=True) * 160
    silence = b"\x00\x00" * int(DEFAULT_PCM_FORMAT.sample_rate * 0.7)
    websocket = FakeAudioWebSocket([speech, silence])
    calls = {}

    class FakeSttService:
        async def transcribe(self, audio_bytes, filename="audio.wav"):
            calls["stt_filename"] = filename
            calls["stt_audio_bytes"] = audio_bytes
            return "Hey Octryx, status?"

    async def fake_get_stt_service(db):
        return FakeSttService()

    async def fake_agent_response(*, text, call_id, channel_id, db, project_id=None):
        calls["agent"] = {
            "text": text,
            "call_id": call_id,
            "channel_id": channel_id,
            "project_id": project_id,
        }
        return "Status is green."

    async def fake_tts_to_pcm(text, db, project_id=None):  # the Workspace is passed
        calls["tts_text"] = text
        return b"tts-audio"

    monkeypatch.setattr(teams_calling, "get_stt_service", fake_get_stt_service)
    monkeypatch.setattr(teams_calling, "agent_response", fake_agent_response)
    monkeypatch.setattr(teams_calling, "tts_to_pcm", fake_tts_to_pcm)

    await call_audio_ws(
        call_id="call-1",
        ws=websocket,
        project_id=str(channel.project_id),
        channel_id=str(channel.id),
        token=issue_call_audio_token("call-1", channel_id=str(channel.id), project_id=str(channel.project_id)),
        db=db,
    )

    assert websocket.accepted is True
    assert websocket.sent == [b"tts-audio"]
    assert calls["stt_filename"] == "audio.wav"
    assert calls["stt_audio_bytes"].startswith(b"RIFF")
    assert calls["agent"] == {
        "text": "status?",
        "call_id": "call-1",
        "channel_id": str(channel.id),
        "project_id": str(channel.project_id),
    }
    assert calls["tts_text"] == "Status is green."


@pytest.mark.asyncio
async def test_call_audio_ws_transcribes_without_responding_when_wake_word_missing(db, monkeypatch):
    from app.api.routes.channels import teams_calling

    channel = await _create_teams_calling_channel(db)
    speech = (1000).to_bytes(2, "little", signed=True) * 160
    silence = b"\x00\x00" * int(DEFAULT_PCM_FORMAT.sample_rate * 0.7)
    websocket = FakeAudioWebSocket([speech, silence])
    calls = {"agent_called": False, "tts_called": False}

    class FakeSttService:
        async def transcribe(self, audio_bytes, filename="audio.wav"):
            return "We should discuss the release date."

    async def fake_get_stt_service(db):
        return FakeSttService()

    async def fake_agent_response(**kwargs):
        calls["agent_called"] = True
        return "Should not happen"

    async def fake_tts_to_pcm(text, db, project_id=None):  # the Workspace is passed
        calls["tts_called"] = True
        return b"tts-audio"

    monkeypatch.setattr(teams_calling, "get_stt_service", fake_get_stt_service)
    monkeypatch.setattr(teams_calling, "agent_response", fake_agent_response)
    monkeypatch.setattr(teams_calling, "tts_to_pcm", fake_tts_to_pcm)

    await call_audio_ws(
        call_id="call-1",
        ws=websocket,
        project_id=str(channel.project_id),
        channel_id=str(channel.id),
        token=issue_call_audio_token("call-1", channel_id=str(channel.id), project_id=str(channel.project_id)),
        db=db,
    )

    assert websocket.accepted is True
    assert websocket.sent == []
    assert calls == {"agent_called": False, "tts_called": False}
