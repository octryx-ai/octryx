"""Server-rendered admin pages that have no SPA replacement yet: settings and the live call monitor."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.web._context import templates
from app.web._helpers._admin_context import _build_settings_context
from app.web._helpers.auth import _require_user

_LOGIN_TARGET = "/chat/login"

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        user = await _require_user(request, db)
    except HTTPException:
        return RedirectResponse(url=_LOGIN_TARGET, status_code=303)

    context = await _build_settings_context(request, db, user=user)
    return templates.TemplateResponse(request, "settings.html", context)


@router.get("/calls", response_class=HTMLResponse)
async def calls_monitor_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Live call monitoring/debugging page."""
    try:
        user = await _require_user(request, db)
    except HTTPException:
        return RedirectResponse(url=_LOGIN_TARGET, status_code=303)
    return templates.TemplateResponse(request, "calls.html", {"user": user})
