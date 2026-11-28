"""Admin panel routes for channel stats, branding and the text-to-speech and speech-to-text configuration."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._connectors import BrandingUpdateRequest
from app.schemas.admin.admin_stt_panel import STTConfigUpdateRequest
from app.schemas.admin.admin_tts_panel import TTSMaskedConfigUpdateRequest
from app.services.admin.panel._admin_misc_core import channel_stats as admin_channel_stats
from app.services.admin.panel._admin_misc_core import get_branding as admin_get_branding
from app.services.admin.panel._admin_misc_core import update_branding as admin_update_branding
from app.services.admin.panel._admin_misc_speech import get_stt_config as admin_get_stt_config
from app.services.admin.panel._admin_misc_speech import get_tts_masked_config as admin_get_tts_masked_config
from app.services.admin.panel._admin_misc_speech import save_stt_config as admin_save_stt_config
from app.services.admin.panel._admin_misc_speech import save_tts_masked_config as admin_save_tts_masked_config
from app.services.secret import get_secret_value, set_secret_value
from app.web._helpers.api_guards import _require_admin_api, _require_api_user
from app.web._helpers.chat_state import _load_branding_config, _save_branding_config

router = APIRouter()


@router.get("/chat/api/panel/channels/{channel_id}/stats")
async def panel_channel_stats(channel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Return aggregated usage stats for all sessions belonging to a channel instance."""
    await _require_admin_api(request, db)
    return JSONResponse(await admin_channel_stats(db, channel_id=channel_id))


@router.get("/chat/api/panel/branding")
async def panel_get_branding(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_api_user(request, db)
    return JSONResponse(admin_get_branding(load_branding_config_func=_load_branding_config))


@router.put("/chat/api/panel/branding")
async def panel_update_branding(
    payload: BrandingUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        admin_update_branding(payload=payload.model_dump(), save_branding_config_func=_save_branding_config)
    )


@router.get("/chat/api/panel/tts/config")
async def panel_tts_get_config(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_tts_masked_config(db, get_secret_value_func=get_secret_value))


@router.put("/chat/api/panel/tts/config")
async def panel_tts_save_config(
    payload: TTSMaskedConfigUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_save_tts_masked_config(
            db,
            payload=payload.model_dump(exclude_none=True),
            set_secret_value_func=set_secret_value,
        )
    )



@router.get("/chat/api/panel/stt/config")
async def panel_stt_get_config(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(await admin_get_stt_config(db, get_secret_value_func=get_secret_value))


@router.put("/chat/api/panel/stt/config")
async def panel_stt_save_config(
    payload: STTConfigUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_save_stt_config(
            db,
            payload=payload.model_dump(exclude_none=True),
            set_secret_value_func=set_secret_value,
        )
    )
