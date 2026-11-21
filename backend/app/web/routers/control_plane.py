"""Auto-extracted router module: control_plane."""

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.admin.provider._admin_control_plane_copilot import (
    complete_control_plane_copilot_device,
    start_control_plane_copilot_device,
)
from app.services.admin.provider.admin_control_plane_service import save_control_plane_provider
from app.services.control_plane.service_helpers import provider_secret_scope
from app.services.control_plane_service import (
    build_provider_client_kwargs_async,
    ensure_control_plane_defaults,
    sync_primary_runtime_target,
    upsert_runtime_target,
)
from app.services.copilot_oauth import (
    begin_copilot_device_flow,
    fetch_github_user_profile,
    poll_copilot_device_flow,
)
from app.services.error_facts import error_text
from app.services.secret import set_secret_value
from app.services.system_config import get_agent_default_model
from app.web._context import templates
from app.web._helpers.auth import COPILOT_DEVICE_FLOW_STATE
from app.web._helpers.control_plane import _build_control_plane_context

from ._control_plane_access import _require_control_plane_admin_or_login_redirect
from .control_plane_runtime_targets import router as control_plane_runtime_targets_router

router = APIRouter()


@router.get("/control-plane", response_class=HTMLResponse)
async def control_plane_settings(
    request: Request,
    provider_id: str | None = None,
    new: bool = False,
    db: AsyncSession = Depends(get_db),
):
    user, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response

    context = await _build_control_plane_context(request, db, edit_provider_id=provider_id, new_provider=new)
    return templates.TemplateResponse(
        request,
        "control_plane.html",
        {
            "user": user,
            **context,
        },
    )


@router.post("/control-plane/save")
async def control_plane_save(
    request: Request,
    provider_id: str = Form(""),
    driver: str = Form(...),
    display_name: str = Form(""),
    auth_mode: str = Form("api_key"),
    api_key: str = Form(""),
    aws_region: str = Form(""),
    aws_role_arn: str = Form(""),
    is_active: str | None = Form(None),
    set_as_active: str | None = Form(None),
    model_id: str = Form(""),
    sync_models: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    _, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response
    from ...agent.providers import get_provider

    updated_provider_id = await save_control_plane_provider(
        db,
        provider_id=provider_id,
        driver=driver,
        display_name=display_name,
        auth_mode=auth_mode,
        api_key=api_key,
        aws_region=aws_region,
        aws_role_arn=aws_role_arn,
        is_active=is_active == "true",
        set_as_active=set_as_active == "true",
        model_id=model_id,
        sync_models=sync_models == "true",
        ensure_control_plane_defaults_func=ensure_control_plane_defaults,
        upsert_runtime_target_func=upsert_runtime_target,
        sync_primary_runtime_target_func=sync_primary_runtime_target,
        provider_secret_scope_func=provider_secret_scope,
        set_secret_value_func=set_secret_value,
        build_provider_client_kwargs_async_func=build_provider_client_kwargs_async,
        get_provider_func=get_provider,
        default_model_id=await get_agent_default_model(db),
    )
    return RedirectResponse(url=f"/admin/control-plane?provider_id={updated_provider_id}", status_code=303)


@router.post("/control-plane/copilot/device/start")
async def control_plane_copilot_device_start(
    request: Request,
    provider_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    _, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response

    try:
        flow_id = await start_control_plane_copilot_device(
            db,
            provider_id=provider_id,
            begin_flow_func=begin_copilot_device_flow,
            flow_state=COPILOT_DEVICE_FLOW_STATE,
        )
    except HTTPException:
        return RedirectResponse(url="/admin/control-plane?error=Copilot+provider+not+found", status_code=303)
    except Exception as exc:
        failure = quote_plus(f"Copilot device flow could not be started. {error_text('device_flow_start_failed', exc)}")
        return RedirectResponse(
            url=f"/admin/control-plane?provider_id={provider_id}&error={failure}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/admin/control-plane?provider_id={provider_id}&copilot_flow_id={flow_id}",
        status_code=303,
    )


@router.post("/control-plane/copilot/device/complete")
async def control_plane_copilot_device_complete(
    request: Request,
    provider_id: str = Form(...),
    flow_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    _, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response

    try:
        result = await complete_control_plane_copilot_device(
            db,
            provider_id=provider_id,
            flow_id=flow_id,
            flow_state=COPILOT_DEVICE_FLOW_STATE,
            poll_flow_func=poll_copilot_device_flow,
            provider_secret_scope_func=provider_secret_scope,
            set_secret_value_func=set_secret_value,
            fetch_profile_func=fetch_github_user_profile,
        )
    except HTTPException:
        return RedirectResponse(url="/admin/control-plane?error=Copilot+login+flow+not+found", status_code=303)
    except Exception as exc:
        failure = error_text("device_flow_complete_failed", exc)
        flow = COPILOT_DEVICE_FLOW_STATE.get(flow_id)
        if flow is not None:
            flow["status"] = "failed"
            flow["error"] = failure
        return RedirectResponse(
            url=(
                f"/admin/control-plane?provider_id={provider_id}&copilot_flow_id={flow_id}"
                f"&error={quote_plus(f'Copilot login could not be completed. {failure}')}"
            ),
            status_code=303,
        )

    if result["status"] == "connected":
        return RedirectResponse(
            url=f"/admin/control-plane?provider_id={result['provider_id']}&notice=GitHub+Copilot+connected",
            status_code=303,
        )
    redirect_suffix = f"&error={quote_plus(result['error'])}" if result.get("error") else ""
    return RedirectResponse(
        url=f"/admin/control-plane?provider_id={result['provider_id']}&copilot_flow_id={flow_id}{redirect_suffix}",
        status_code=303,
    )


router.include_router(control_plane_runtime_targets_router)
