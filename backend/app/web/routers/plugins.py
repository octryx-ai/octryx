"""The server-rendered ``/admin`` plugin and MCP pages (global admin only)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.error_facts import error_facts
from app.web._context import templates
from app.web._helpers.page_admin_guard import LoginRequiredError, require_page_admin

router = APIRouter()


@router.get("/plugins", response_class=HTMLResponse)
async def plugins_page(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user = await require_page_admin(request, db)
    except LoginRequiredError:
        return RedirectResponse(url="/chat/login", status_code=303)

    try:
        from ...plugins.core.manager import get_all_discovered_plugins, load_plugins

        load_plugins()
        plugins = get_all_discovered_plugins()
    except Exception:
        plugins = []

    return templates.TemplateResponse(
        request,
        "plugins.html",
        {
            "user": user,
            "plugins": plugins,
            "error": None,
        },
    )


@router.post("/plugins/reload")
async def plugins_reload(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await require_page_admin(request, db)
    except LoginRequiredError:
        return RedirectResponse(url="/chat/login", status_code=303)

    try:
        from ...plugins.core.manager import get_all_discovered_plugins, reload_plugins

        reload_plugins()
        plugins = get_all_discovered_plugins()
        return {"success": True, "plugins": plugins}
    except Exception as e:
        return {"success": False, "error": "Plugins could not be reloaded.", **error_facts("plugin_reload_failed", e)}


@router.post("/plugins/{plugin_id}/enable")
async def plugins_enable(plugin_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await require_page_admin(request, db)
    except LoginRequiredError:
        return RedirectResponse(url="/chat/login", status_code=303)

    try:
        from ...plugins.core.manager import enable_plugin, get_all_discovered_plugins, reload_plugins

        enable_plugin(plugin_id)
        reload_plugins()
        plugins = get_all_discovered_plugins()
        return {"success": True, "plugins": plugins}
    except Exception as e:
        return {"success": False, "error": "Plugin could not be enabled.", **error_facts("plugin_enable_failed", e)}


@router.post("/plugins/{plugin_id}/disable")
async def plugins_disable(plugin_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        await require_page_admin(request, db)
    except LoginRequiredError:
        return RedirectResponse(url="/chat/login", status_code=303)

    try:
        from ...plugins.core.manager import disable_plugin, get_all_discovered_plugins

        disable_plugin(plugin_id)
        plugins = get_all_discovered_plugins()
        return {"success": True, "plugins": plugins}
    except Exception as e:
        return {"success": False, "error": "Plugin could not be disabled.", **error_facts("plugin_disable_failed", e)}
