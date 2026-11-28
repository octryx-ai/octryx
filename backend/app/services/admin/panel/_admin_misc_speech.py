"""Admin-panel speech settings: masked TTS/STT secrets and the STT provider configuration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

_MASK = "••••••••"
_SETTINGS_VIEW = "admin.speech_settings"


async def get_tts_masked_config(
    db: AsyncSession,
    *,
    get_secret_value_func: Callable[..., Any],
) -> dict[str, Any]:
    tts_keys = [
        "openai_api_key",
        "elevenlabs_api_key",
        "aws_access_key_id",
        "aws_secret_access_key",
    ]
    result: dict[str, str] = {}
    for key in tts_keys:
        value = await get_secret_value_func(db, tool_name="tts", field_name=key, project_id=None,
                                            purpose=_SETTINGS_VIEW)
        public_key = {
            "aws_access_key_id": "aws_polly_access_key_id",
            "aws_secret_access_key": "aws_polly_secret_key",
        }.get(key, key)
        result[public_key] = _MASK if value else ""
    stt_val = await get_secret_value_func(db, tool_name="stt", field_name="openai_api_key", project_id=None,
                                         purpose=_SETTINGS_VIEW)
    result["stt_openai_api_key"] = _MASK if stt_val else ""
    return result


async def get_stt_config(
    db: AsyncSession,
    *,
    get_secret_value_func: Callable[..., Any],
) -> dict[str, Any]:
    async def stt(field_name: str) -> Any:
        return await get_secret_value_func(db, tool_name="stt", field_name=field_name, project_id=None,
                                           purpose=_SETTINGS_VIEW)

    # Determine active provider by checking what's configured (same priority as get_stt_service)
    whisper_url = await stt("whisper_base_url")
    aws_key = await stt("aws_access_key_id")
    azure_key = await stt("azure_subscription_key")
    openai_key = await stt("openai_api_key")
    active_provider = _active_stt_provider(whisper_url, aws_key, azure_key, openai_key)

    # Language (shared setting)
    language = await stt("language")

    # Provider-specific non-secret settings, read in this order
    providers_config: dict[str, Any] = {
        "local_whisper": await _url_provider_config(stt, "whisper", whisper_url, default_model="base"),
        "aws_transcribe": await _aws_transcribe_config(stt, aws_key),
        "azure_speech": await _azure_speech_config(stt, azure_key),
        "openai_whisper": {
            "configured": bool(openai_key),
            "api_key": _MASK if openai_key else "",
        },
    }

    return {
        "active_provider": active_provider,
        "language": language or "",
        "providers": providers_config,
    }


def _active_stt_provider(whisper_url: Any, aws_key: Any, azure_key: Any, openai_key: Any) -> Any:
    if whisper_url:
        return "local_whisper"
    if aws_key:
        return "aws_transcribe"
    if azure_key:
        return "azure_speech"
    if openai_key:
        return "openai_whisper"
    return None


async def _url_provider_config(stt: Callable[[str], Any], prefix: str, base_url: Any, *, default_model: str) -> dict:
    return {
        "configured": bool(base_url),
        "base_url": base_url or "",
        "api_key": _MASK if await stt(f"{prefix}_api_key") else "",
        "model": await stt(f"{prefix}_model") or default_model,
        "endpoint_path": await stt(f"{prefix}_endpoint_path") or "/v1/audio/transcriptions",
    }


async def _aws_transcribe_config(stt: Callable[[str], Any], aws_key: Any) -> dict:
    return {
        "configured": bool(aws_key),
        "access_key_id": _MASK if aws_key else "",
        "secret_access_key": _MASK if await stt("aws_secret_access_key") else "",
        "region": await stt("aws_region") or "eu-central-1",
        "language_code": await stt("aws_language_code") or "",
        "enable_diarization": (await stt("aws_enable_diarization") or "true") != "false",
    }


async def _azure_speech_config(stt: Callable[[str], Any], azure_key: Any) -> dict:
    return {
        "configured": bool(azure_key),
        "subscription_key": _MASK if azure_key else "",
        "region": await stt("azure_region") or "westeurope",
        "language": await stt("azure_language") or "",
        "enable_diarization": (await stt("azure_enable_diarization") or "true") != "false",
    }


# Secret field names per STT provider: (payload key, stored field name), queued in this order.
_STT_PROVIDER_FIELDS = (
    (
        "local_whisper",
        (
            ("base_url", "whisper_base_url"),
            ("api_key", "whisper_api_key"),
            ("model", "whisper_model"),
            ("endpoint_path", "whisper_endpoint_path"),
        ),
        None,
    ),
    (
        "aws_transcribe",
        (
            ("access_key_id", "aws_access_key_id"),
            ("secret_access_key", "aws_secret_access_key"),
            ("region", "aws_region"),
            ("language_code", "aws_language_code"),
        ),
        "aws_enable_diarization",
    ),
    (
        "azure_speech",
        (
            ("subscription_key", "azure_subscription_key"),
            ("region", "azure_region"),
            ("language", "azure_language"),
        ),
        "azure_enable_diarization",
    ),
    ("openai_whisper", (("api_key", "openai_api_key"),), None),
)


async def save_stt_config(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    set_secret_value_func: Callable[..., Any],
) -> dict[str, Any]:
    # Save shared language
    language = payload.get("language", "")
    if language:
        await set_secret_value_func(db, tool_name="stt", field_name="language", project_id=None, value=language)

    providers = payload.get("providers", {})
    _saves: list = []
    for provider_key, fields, diarization_field in _STT_PROVIDER_FIELDS:
        provider_data = providers.get(provider_key, {})
        if not provider_data:
            continue
        for src_key, field_name in fields:
            _collect_save(provider_data, src_key, field_name, "stt", set_secret_value_func, db, _saves)
        if diarization_field and "enable_diarization" in provider_data:
            _saves.append(
                set_secret_value_func(
                    db, tool_name="stt", field_name=diarization_field,
                    project_id=None, value="true" if provider_data["enable_diarization"] else "false"
                )
            )

    # Execute all pending saves
    for coro in _saves:
        await coro

    await db.commit()
    return {"saved": True}


def _collect_save(provider_data, src_key, field_name, tool_name, set_func, db, saves_list):
    value = provider_data.get(src_key, "")
    if value and not str(value).startswith("••"):
        saves_list.append(
            set_func(db, tool_name=tool_name, field_name=field_name, project_id=None, value=str(value))
        )


async def save_tts_masked_config(
    db: AsyncSession,
    *,
    payload: dict[str, Any],
    set_secret_value_func: Callable[..., Any],
) -> dict[str, Any]:
    for public_key, secret_key in {
        "openai_api_key": "openai_api_key",
        "elevenlabs_api_key": "elevenlabs_api_key",
        "aws_polly_access_key_id": "aws_access_key_id",
        "aws_polly_secret_key": "aws_secret_access_key",
    }.items():
        value = payload.get(public_key, "")
        if value and not str(value).startswith("••"):
            await set_secret_value_func(db, tool_name="tts", field_name=secret_key, project_id=None, value=value)
    stt_val = payload.get("stt_openai_api_key", "")
    if stt_val and not str(stt_val).startswith("••"):
        await set_secret_value_func(db, tool_name="stt", field_name="openai_api_key", project_id=None, value=stt_val)
    await db.commit()
    return {"saved": True}
