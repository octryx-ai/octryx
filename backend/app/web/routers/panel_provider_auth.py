"""Admin panel routes for provider sign-in: the Copilot device flow and the Google OAuth flow."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_runtime_panel import CopilotDevicePollRequest
from app.services.admin.provider.admin_copilot_service import (
    poll_copilot_device_login as admin_poll_copilot_device_login,
)
from app.services.admin.provider.admin_copilot_service import (
    start_copilot_device_flow as admin_start_copilot_device_flow,
)
from app.services.control_plane.service_helpers import provider_secret_scope
from app.services.copilot_oauth import (
    begin_copilot_device_flow,
    fetch_github_user_profile,
    poll_copilot_device_flow,
)
from app.services.google_provider_oauth import (
    build_google_provider_authorization_redirect,
    complete_google_provider_oauth_callback,
)
from app.services.secret import set_secret_value
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.auth import COPILOT_DEVICE_FLOW_STATE

from .panel_runtime_settings import router as panel_runtime_settings_router

router = APIRouter()


@router.post("/chat/api/panel/providers/{provider_id}/copilot/device/start")
async def panel_copilot_device_start(provider_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_start_copilot_device_flow(
            db,
            provider_id=provider_id,
            flow_state=COPILOT_DEVICE_FLOW_STATE,
            begin_flow_func=begin_copilot_device_flow,
        )
    )


@router.post("/chat/api/panel/providers/{provider_id}/copilot/device/poll")
async def panel_copilot_device_poll(
    provider_id: str,
    payload: CopilotDevicePollRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await admin_poll_copilot_device_login(
            db,
            provider_id=provider_id,
            flow_id=payload.flow_id,
            flow_state=COPILOT_DEVICE_FLOW_STATE,
            poll_flow_func=poll_copilot_device_flow,
            provider_secret_scope_func=provider_secret_scope,
            set_secret_value_func=set_secret_value,
            fetch_profile_func=fetch_github_user_profile,
        )
    )


@router.get("/chat/api/panel/providers/{provider_id}/google/oauth/start")
async def panel_google_provider_oauth_start(
    provider_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin_api(request, db)
    authorization_url = await build_google_provider_authorization_redirect(
        db,
        llm_provider_id=provider_id,
        redirect_uri=str(request.url_for("panel_google_provider_oauth_callback")),
        requested_by_user_id=user.id,
    )
    return RedirectResponse(url=authorization_url, status_code=307)


@router.get("/chat/api/panel/providers/google/oauth/callback", name="panel_google_provider_oauth_callback")
async def panel_google_provider_oauth_callback(
    request: Request,
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google provider login failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Google provider callback missing authorization code")
    result = await complete_google_provider_oauth_callback(
        db,
        state=state,
        code=code,
        redirect_uri=str(request.url_for("panel_google_provider_oauth_callback")),
    )
    return RedirectResponse(url=result["redirect_path"], status_code=303)


router.include_router(panel_runtime_settings_router)
