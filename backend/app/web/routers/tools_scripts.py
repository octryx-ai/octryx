"""The server-rendered ``/admin/tools`` panel: built-in tool configs and saved Python scripts.

Every route is admin-only: a tool config names where a stored credential is sent and a
saved script is code the platform runs, so an active non-admin user is refused with 403. A save
or connection test that would move a kept secret to a changed target is refused with the explicit
state ``secret_rebind_required`` (``services/tool_config/secret_rebind.py``).
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import SavedPythonScript
from app.services.access_control import require_existing_workspace
from app.services.connector_test_service import run_connector_connection_test
from app.services.script import delete_saved_script, save_python_script
from app.services.secret import resolve_secret_refs, secret_ref_label
from app.services.tool_config import upsert_tool_config
from app.services.tool_config.secret_rebind import SecretRebindRequiredError
from app.web._context import templates
from app.web._helpers._tool_config_payload import _build_tool_config_payload
from app.web._helpers.control_plane import _build_tools_context
from app.web._helpers.page_admin_guard import LoginRequiredError, require_page_admin

router = APIRouter()


def _login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/chat/login", status_code=303)


def _refuse_secret_rebind(refused: SecretRebindRequiredError) -> JSONResponse:
    """Nothing of the request was kept; the refusal's audit row (names only) is already committed."""
    return JSONResponse(status_code=409, content={"detail": refused.detail()})


@router.get("/tools", response_class=HTMLResponse)
async def tools_page(
    request: Request,
    script_id: str | None = None,
    project_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await require_page_admin(request, db)
    except LoginRequiredError:
        return _login_redirect()
    context = await _build_tools_context(request, db, user=user, script_id=script_id, project_id=project_id)
    return templates.TemplateResponse(request, "tools.html", context)


@router.post("/tools/scripts/save")
async def tools_script_save(
    request: Request,
    script_id: str = Form(""),
    name: str = Form(...),
    purpose: str = Form(...),
    description: str = Form(""),
    code: str = Form(...),
    is_active: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await require_page_admin(request, db)
    except LoginRequiredError:
        return _login_redirect()

    existing_script = await db.get(SavedPythonScript, script_id) if script_id else None
    if existing_script and existing_script.name != name.strip():
        await delete_saved_script(db, existing_script.id)
        await db.flush()

    script = await save_python_script(
        db,
        user_id=user.id,
        name=name,
        purpose=purpose,
        code=code,
        description=description,
        is_active=is_active == "true",
    )
    await db.commit()
    return RedirectResponse(url=f"/admin/tools?script_id={script.id}", status_code=303)


@router.post("/tools/scripts/delete/{script_id}")
async def tools_script_delete(
    script_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        await require_page_admin(request, db)
    except LoginRequiredError:
        return _login_redirect()

    await delete_saved_script(db, script_id)
    await db.commit()
    return RedirectResponse(url="/admin/tools", status_code=303)


@router.post("/tools/configs/save")
async def tools_config_save(
    request: Request,
    tool_name: str = Form(...),
    project_id: str = Form(""),
    config_json: str = Form("{}"),
    description: str = Form(""),
    is_active: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await require_page_admin(request, db)
    except LoginRequiredError:
        return _login_redirect()
    await require_existing_workspace(db, project_id or None)
    try:
        parsed_config = await _build_tool_config_payload(
            request,
            db,
            tool_name=tool_name,
            project_id=project_id or None,
            config_json=config_json,
            actor_user_id=user.id,
        )
    except SecretRebindRequiredError as refused:
        return _refuse_secret_rebind(refused)

    await upsert_tool_config(
        db,
        tool_name=tool_name,
        project_id=project_id or None,
        config=parsed_config,
        description=description,
        is_active=is_active == "true",
    )
    await db.commit()
    redirect_suffix = f"?project_id={project_id}" if project_id else ""
    return RedirectResponse(url=f"/admin/tools{redirect_suffix}", status_code=303)


@router.post("/tools/configs/test", response_class=HTMLResponse)
async def tools_config_test(
    request: Request,
    tool_name: str = Form(...),
    project_id: str = Form(""),
    config_json: str = Form("{}"),
    description: str = Form(""),
    is_active: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await require_page_admin(request, db)
    except LoginRequiredError:
        return _login_redirect()
    await require_existing_workspace(db, project_id or None)
    try:
        parsed_config = await _build_tool_config_payload(
            request,
            db,
            tool_name=tool_name,
            project_id=project_id or None,
            config_json=config_json,
            actor_user_id=user.id,
            # A test never stores a typed secret; the saved one stays untouched.
            persist_secrets=False,
        )
    except SecretRebindRequiredError as refused:
        return _refuse_secret_rebind(refused)
    resolved_config = await resolve_secret_refs(db, parsed_config, tool_name=tool_name, project_id=project_id or None)

    context = await _build_tools_context(
        request,
        db,
        user=user,
        project_id=project_id,
        tool_test_results={tool_name: await run_connector_connection_test(tool_name, resolved_config, db=db)},
    )
    for form in context["tool_config_forms"]:
        if form["tool_name"] == tool_name:
            form["config_json"] = config_json
            form["is_active"] = is_active == "true"
            form["description_value"] = description.strip()
            form["secret_refs"] = {
                field_name: parsed_config.get(f"{field_name}_secret_ref")
                for field_name in form.get("secret_fields", [])
                if parsed_config.get(f"{field_name}_secret_ref")
            }
            form["secret_ref_labels"] = {
                field_name: secret_ref_label(secret_id) for field_name, secret_id in form["secret_refs"].items()
            }
            break
    return templates.TemplateResponse(request, "tools.html", context)
