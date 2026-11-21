"""Control plane page routes for runtime targets and the diagnosis test chat.

Included by ``control_plane.router``.
"""

import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.engine import run_agent
from app.db import get_db
from app.models import Session as AgentSession
from app.services.admin.provider._admin_control_plane_targets import (
    delete_control_plane_runtime_target,
    move_control_plane_runtime_target,
    save_control_plane_runtime_target,
    toggle_control_plane_runtime_target,
)
from app.services.control_plane_service import (
    delete_runtime_target,
    move_runtime_target,
    toggle_runtime_target,
    upsert_runtime_target,
)
from app.services.error_facts import error_text
from app.services.run_capability.worker_profiles import worker_session_capability_metadata
from app.web._context import templates
from app.web._helpers.control_plane import _build_control_plane_context

from ._control_plane_access import _require_control_plane_admin_or_login_redirect

router = APIRouter()


@router.post("/control-plane/runtime-targets/save")
async def control_plane_runtime_target_save(
    request: Request,
    provider_id: str = Form(...),
    model_id: str = Form(...),
    make_primary: str | None = Form(None),
    is_active: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    user, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response
    updated_provider_id = await save_control_plane_runtime_target(
        db,
        provider_id=provider_id,
        model_id=model_id,
        make_primary=make_primary == "true",
        is_active=is_active == "true",
        upsert_runtime_target_func=upsert_runtime_target,
        actor_user_id=user.id,
    )
    return RedirectResponse(
        url=f"/admin/control-plane?provider_id={updated_provider_id}#runtime-targets", status_code=303
    )


@router.post("/control-plane/runtime-targets/{target_id}/move")
async def control_plane_runtime_target_move(
    target_id: str,
    request: Request,
    direction: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response
    await move_control_plane_runtime_target(
        db,
        target_id=target_id,
        direction=direction,
        move_runtime_target_func=move_runtime_target,
        actor_user_id=user.id,
    )
    return RedirectResponse(url="/admin/control-plane#runtime-targets", status_code=303)


@router.post("/control-plane/runtime-targets/{target_id}/toggle")
async def control_plane_runtime_target_toggle(
    target_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response
    await toggle_control_plane_runtime_target(
        db,
        target_id=target_id,
        toggle_runtime_target_func=toggle_runtime_target,
        actor_user_id=user.id,
    )
    return RedirectResponse(url="/admin/control-plane#runtime-targets", status_code=303)


@router.post("/control-plane/runtime-targets/{target_id}/delete")
async def control_plane_runtime_target_delete(
    target_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response
    await delete_control_plane_runtime_target(
        db,
        target_id=target_id,
        delete_runtime_target_func=delete_runtime_target,
        actor_user_id=user.id,
    )
    return RedirectResponse(url="/admin/control-plane#runtime-targets", status_code=303)


@router.post("/control-plane/test-chat")
async def control_plane_test_chat(
    request: Request,
    prompt: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user, redirect_response = await _require_control_plane_admin_or_login_redirect(request, db)
    if redirect_response is not None:
        return redirect_response

    context = await _build_control_plane_context(request, db, test_prompt=prompt)
    test_response = None
    test_error = None

    session = AgentSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=None,
        agent_type="diagnosis",
        status="active",
        origin="control_plane_test",
        metadata_=worker_session_capability_metadata("control_plane_test_chat"),
    )
    db.add(session)
    await db.flush()

    try:
        async for event in run_agent(
            session_id=session.id,
            user_message=prompt,
            user_id=user.id,
            project_id=None,
            agent_type="diagnosis",
            db=db,
        ):
            if event.role == "assistant" and event.content is not None:
                test_response = event.content
    except Exception as exc:
        test_error = f"The diagnosis agent run failed. {error_text('diagnosis_run_failed', exc)}"

    if not test_response and not test_error:
        test_error = "No assistant response returned."

    await db.commit()
    context.update(
        {
            "test_prompt": prompt,
            "test_response": test_response,
            "test_error": test_error,
        }
    )
    return templates.TemplateResponse(
        request,
        "control_plane.html",
        {
            "user": user,
            **context,
        },
    )
