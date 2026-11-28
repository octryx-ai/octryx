"""A device fetches the archive a job offered it and uploads a large result, with its own device token
(``services/devices/tree_archive``): another device, an expired or unknown archive is a 404, never a hint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.devices import tree_archive
from ....services.devices.credential import resolve_device_credential
from .device_session_state import router as session_state_router

router = APIRouter(tags=["device-archives"])
router.include_router(session_state_router)


async def _device_id(request: Request, db: AsyncSession) -> str | None:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    credential = await resolve_device_credential(db, header[7:].strip())
    return None if isinstance(credential, str) else str(credential.device.id)


@router.get("/api/v1/devices/archives/{ident}")
async def get_archive(ident: str, request: Request, db: AsyncSession = Depends(get_db)):
    device_id = await _device_id(request, db)
    data = tree_archive.fetch(ident, device_id) if device_id else None
    if data is None:
        return JSONResponse({"detail": {"code": "archive_not_found", "message": "no such archive for this device; "
                                        "instead: ask the job again"}}, status_code=404)
    return Response(content=data, media_type="application/gzip")


@router.post("/api/v1/devices/uploads")
async def post_upload(request: Request, name: str = Query("result", max_length=120),
                      db: AsyncSession = Depends(get_db)):
    device_id = await _device_id(request, db)
    if device_id is None:
        return JSONResponse({"detail": {"code": "device_token_required", "message": "a device token is required; "
                                        "instead: sign the device in again"}}, status_code=401)
    data = await request.body()
    found = tree_archive.accept_upload(data, device_id=device_id, name=name)
    if isinstance(found, str):
        return JSONResponse({"detail": {"code": "upload_too_large", "message": f"{found}; instead: send less"}},
                            status_code=413)
    return found
