import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.secret import set_secret_value
from app.services.stt import (
    OpenAICompatibleSTTService,
    STTService,
    get_stt_service,
    resolve_stt_service,
)
from app.services.stt import service as stt_service


class FakeAsyncClient:
    requests: list[dict] = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, headers=None, files=None, data=None):
        self.requests.append(
            {
                "url": url,
                "headers": headers or {},
                "files": files or {},
                "data": data or {},
            }
        )
        return httpx.Response(
            200,
            json={"text": "ping pong"},
            headers={"content-type": "application/json"},
            request=httpx.Request("POST", url),
        )


@pytest.mark.asyncio
async def test_get_stt_service_selects_local_whisper(db):
    await set_secret_value(db, tool_name="stt", field_name="whisper_base_url", project_id=None, value="http://whisper.test")
    await set_secret_value(db, tool_name="stt", field_name="whisper_model", project_id=None, value="base")
    await db.commit()

    provider = await get_stt_service(db)

    assert isinstance(provider, OpenAICompatibleSTTService)
    assert provider.provider_name == "local_whisper"
    assert provider.base_url == "http://whisper.test"
    assert provider.model == "base"


@pytest.mark.asyncio
async def test_get_stt_service_rejects_invalid_local_whisper_base_url(db):
    await set_secret_value(db, tool_name="stt", field_name="whisper_base_url", project_id=None, value="file:///tmp/whisper")
    await db.commit()

    assert await get_stt_service(db) is None


@pytest.mark.asyncio
async def test_get_stt_service_falls_back_when_local_whisper_config_is_invalid(db):
    await set_secret_value(db, tool_name="stt", field_name="whisper_base_url", project_id=None, value="file:///tmp/whisper")
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    provider = await get_stt_service(db)

    assert isinstance(provider, STTService)
    assert provider.provider_name == "openai_whisper"


@pytest.mark.asyncio
async def test_resolve_stt_service_exposes_fallback_attempts(db):
    await set_secret_value(db, tool_name="stt", field_name="whisper_base_url", project_id=None, value="file:///tmp/whisper")
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    resolution = await resolve_stt_service(db)

    assert isinstance(resolution.service, STTService)
    assert resolution.selected_provider == "openai_whisper"
    assert resolution.fallback_allowed is True
    assert resolution.fallback_used is True
    assert resolution.to_audit_dict()["attempts"][0] == {
        "provider": "local_whisper",
        "status": "failed",
        "reason": "invalid_configuration",
    }


@pytest.mark.asyncio
async def test_resolve_stt_service_can_disable_fallback_after_configured_failure(db):
    await set_secret_value(db, tool_name="stt", field_name="allow_provider_fallback", project_id=None, value="false")
    await set_secret_value(db, tool_name="stt", field_name="whisper_base_url", project_id=None, value="file:///tmp/whisper")
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    resolution = await resolve_stt_service(db)

    assert resolution.service is None
    assert resolution.selected_provider is None
    assert resolution.fallback_allowed is False
    assert resolution.fallback_used is False
    assert resolution.to_audit_dict()["attempts"][-1] == {
        "provider": "fallback_policy",
        "status": "blocked",
        "reason": "fallback_disabled_after_configured_failure",
    }


@pytest.mark.asyncio
async def test_get_stt_service_falls_back_to_openai(db):
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    provider = await get_stt_service(db)

    assert isinstance(provider, STTService)
    assert provider.provider_name == "openai_whisper"


@pytest.mark.asyncio
async def test_stt_status_exposes_resolution(client, auth_headers, db):
    await set_secret_value(db, tool_name="stt", field_name="whisper_base_url", project_id=None, value="file:///tmp/whisper")
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    response = await client.get("/api/v1/stt/status", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["provider"] == "openai_whisper"
    assert payload["fallback_allowed"] is True
    assert payload["fallback_used"] is True
    assert payload["resolution"]["selected_provider"] == "openai_whisper"


@pytest.mark.asyncio
async def test_stt_transcribe_audits_fallback_selection(client, auth_headers, db, monkeypatch):
    async def fake_transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        assert audio_bytes == b"audio-bytes"
        assert filename == "recording.webm"
        return "hello"

    monkeypatch.setattr(stt_service.STTService, "transcribe", fake_transcribe)
    await set_secret_value(db, tool_name="stt", field_name="whisper_base_url", project_id=None, value="file:///tmp/whisper")
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    response = await client.post(
        "/api/v1/stt/transcribe",
        files={"audio": ("recording.webm", b"audio-bytes", "audio/webm")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"text": "hello"}
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "speech.stt.fallback_selected"))
    ).scalar_one()
    assert audit.resource_type == "speech_stt"
    assert audit.resource_id == "openai_whisper"
    assert audit.details["fallback_used"] is True


@pytest.mark.asyncio
async def test_stt_transcribe_reports_provider_unavailable_without_live_provider(client, auth_headers, db):
    response = await client.post(
        "/api/v1/stt/transcribe",
        files={"audio": ("recording.webm", b"audio-bytes", "audio/webm")},
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"].startswith("STT service not configured")
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "speech.stt.provider_unavailable"))
    ).scalar_one()
    assert audit.resource_type == "speech_stt"
    assert audit.resource_id == "none"
    assert audit.details["selected_provider"] is None


@pytest.mark.asyncio
async def test_stt_transcribe_rejects_empty_audio(client, auth_headers, db):
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    response = await client.post(
        "/api/v1/stt/transcribe",
        files={"audio": ("empty.webm", b"", "audio/webm")},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Empty audio file"


@pytest.mark.asyncio
async def test_stt_transcribe_redacts_secret_like_provider_errors(client, auth_headers, db, monkeypatch):
    async def fake_transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        raise RuntimeError("authorization: Bearer sk-supersecrettoken123 api_key=sk-anothersecret456")

    monkeypatch.setattr(stt_service.STTService, "transcribe", fake_transcribe)
    await set_secret_value(db, tool_name="stt", field_name="openai_api_key", project_id=None, value="openai-key")
    await db.commit()

    response = await client.post(
        "/api/v1/stt/transcribe",
        files={"audio": ("recording.webm", b"audio-bytes", "audio/webm")},
        headers=auth_headers,
    )

    assert response.status_code == 502
    response_text = response.text
    assert "sk-supersecrettoken123" not in response_text
    assert "sk-anothersecret456" not in response_text
    assert "[redacted]" in response_text
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "speech.stt.transcription_failed"))
    ).scalar_one()
    assert "sk-supersecrettoken123" not in audit.details["error"]
    assert "sk-anothersecret456" not in audit.details["error"]
    assert "[redacted]" in audit.details["error"]
