"""Admin transport for the configured presentation fallback."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.office.presentation_fallback import (
    InvalidPresentationFallbackModeError,
    describe_effective_presentation_template,
    set_presentation_fallback_mode,
)
from app.web._helpers.api_guards import _require_admin_api

router = APIRouter()


@router.get("/chat/api/panel/office-presentation-fallback")
async def get_office_presentation_fallback(request: Request, db: AsyncSession = Depends(get_db)):
    await _require_admin_api(request, db)
    return await describe_effective_presentation_template(db)


@router.put("/chat/api/panel/office-presentation-fallback")
async def put_office_presentation_fallback(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin_api(request, db)
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {"mode"} or not isinstance(body["mode"], str):
            raise ValueError("invalid_payload")
        await set_presentation_fallback_mode(db, mode=body["mode"], updated_by=user.id)
    except (ValueError, InvalidPresentationFallbackModeError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_presentation_fallback"}) from exc
    await db.commit()
    return await describe_effective_presentation_template(db)
