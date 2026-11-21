from pydantic import ValidationError

from app.schemas.admin.admin_tts_panel import (
    TTSConfigUpdateRequest,
    TTSMaskedConfigUpdateRequest,
    TTSProviderUpsertRequest,
    TTSSynthesizeRequest,
)


def test_tts_request_validation_and_defaults_remain_stable():
    provider_payload = TTSProviderUpsertRequest(provider="openai")
    synth_payload = TTSSynthesizeRequest(text="hello world", speed=4.0)
    masked_payload = TTSMaskedConfigUpdateRequest(openai_api_key="secret", aws_polly_secret_key="aws")

    assert provider_payload.enabled is True
    assert provider_payload.priority == 0
    assert provider_payload.config == {}
    assert synth_payload.speed == 4.0
    assert masked_payload.openai_api_key == "secret"
    assert masked_payload.aws_polly_secret_key == "aws"

    try:
        TTSConfigUpdateRequest(default_speed=4.1)
    except ValidationError as exc:
        assert "default_speed" in str(exc)
    else:
        raise AssertionError("Expected TTS config validation to reject an oversized default speed")
