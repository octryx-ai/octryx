"""The ``/chat/api/v1/tts`` routes: a thin delegation layer over ``app.services.tts``."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_runtime_panel import RuntimeDirectionRequest
from app.schemas.admin.admin_tts_panel import TTSConfigUpdateRequest, TTSProviderUpsertRequest, TTSSynthesizeRequest
from app.web._context import logger
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.get("/chat/api/v1/tts/providers")
async def tts_list_providers(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    from ...services.tts import (
        has_active_tts_provider,
        list_tts_providers,
        load_tts_config,
        resolve_tts_provider,
        serialize_tts_overview,
    )

    providers = await list_tts_providers(db)
    config = await load_tts_config(db)
    resolution = await resolve_tts_provider(db)
    effective_enabled = bool(config.enabled and await has_active_tts_provider(db, config))
    return JSONResponse(
        {
            **serialize_tts_overview(config, resolution, effective_enabled=effective_enabled),
            "providers": providers,
        }
    )


@router.get("/chat/api/v1/tts/config")
async def tts_get_config(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    from ...services.tts import (
        has_active_tts_provider,
        load_tts_config,
        resolve_tts_provider,
        serialize_tts_overview,
        serialize_tts_provider_rows,
    )

    config = await load_tts_config(db)
    resolution = await resolve_tts_provider(db)
    effective_enabled = bool(config.enabled and await has_active_tts_provider(db, config))
    return JSONResponse(
        {
            **serialize_tts_overview(config, resolution, effective_enabled=effective_enabled),
            "providers": serialize_tts_provider_rows(config),
        }
    )


@router.put("/chat/api/v1/tts/config")
async def tts_update_config(
    payload: TTSConfigUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.tts import has_active_tts_provider, load_tts_config, save_tts_config

    config = await load_tts_config(db)
    if payload.enabled is not None:
        config.enabled = payload.enabled
    if payload.default_voice is not None:
        config.default_voice = payload.default_voice
    if payload.default_speed is not None:
        config.default_speed = payload.default_speed
    if payload.allow_provider_fallback is not None:
        config.allow_provider_fallback = payload.allow_provider_fallback
    if config.enabled and not await has_active_tts_provider(db, config):
        raise HTTPException(status_code=400, detail="Install and activate one available TTS provider first.")
    await save_tts_config(db, config)
    return JSONResponse({"status": "ok"})


@router.post("/chat/api/v1/tts/providers")
async def tts_add_provider(
    payload: TTSProviderUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.tts import upsert_tts_provider

    try:
        await upsert_tts_provider(
            db,
            provider=payload.provider,
            enabled=payload.enabled,
            priority=payload.priority,
            config=payload.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse({"status": "ok"})


@router.delete("/chat/api/v1/tts/providers/{provider_id}")
async def tts_remove_provider(request: Request, provider_id: str, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    from ...services.tts import remove_tts_provider

    await remove_tts_provider(db, provider_id=provider_id)
    return JSONResponse({"status": "ok"})


@router.post("/chat/api/v1/tts/providers/{provider_id}/move")
async def tts_move_provider(
    provider_id: str,
    payload: RuntimeDirectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    from ...services.tts import move_tts_provider, serialize_tts_provider_rows

    try:
        config = await move_tts_provider(db, provider_id=provider_id, direction=payload.direction)
    except KeyError:
        raise HTTPException(status_code=404, detail="Provider not found")

    config.providers = sorted(config.providers, key=lambda x: x.priority)
    return JSONResponse({"providers": serialize_tts_provider_rows(config)})


@router.post("/chat/api/v1/tts/synthesize")
async def tts_synthesize(
    payload: TTSSynthesizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    from ...models import AuditLog
    from ...services.tts import load_tts_config, resolve_tts_provider

    text = payload.text
    if not text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    config = await load_tts_config(db)
    if not config.enabled and not payload.provider:
        raise HTTPException(status_code=503, detail="TTS is not enabled. Enable it in Admin panel first.")
    resolution = await resolve_tts_provider(db, payload.provider)
    provider = resolution.provider
    if provider is None:
        db.add(
            AuditLog(
                user_id=user.id,
                action="speech.tts.provider_unavailable",
                resource_type="speech_tts",
                resource_id=resolution.selected_provider or "none",
                details=resolution.to_audit_dict(),
            )
        )
        await db.commit()
        raise HTTPException(status_code=503, detail="No TTS provider configured or available.")
    if resolution.fallback_used:
        db.add(
            AuditLog(
                user_id=user.id,
                action="speech.tts.fallback_selected",
                resource_type="speech_tts",
                resource_id=resolution.selected_provider or "none",
                details=resolution.to_audit_dict(),
            )
        )
        await db.commit()
    voice = payload.voice or config.default_voice
    speed = payload.speed if payload.speed is not None else config.default_speed
    try:
        audio_bytes = await provider.synthesize(text, voice, speed)
    except Exception as exc:
        from ...services.redaction_policy import redact_secret_text

        safe_error = redact_secret_text(exc, max_chars=500)
        logger.warning("TTS synthesis failed: %s", safe_error)
        db.add(
            AuditLog(
                user_id=user.id,
                action="speech.tts.synthesis_failed",
                resource_type="speech_tts",
                resource_id=resolution.selected_provider or "none",
                details={
                    **resolution.to_audit_dict(),
                    "error_type": type(exc).__name__,
                    "error": safe_error,
                },
            )
        )
        await db.commit()
        raise HTTPException(status_code=502, detail=f"TTS provider error: {safe_error}")
    return Response(content=audio_bytes, media_type="audio/mpeg")
