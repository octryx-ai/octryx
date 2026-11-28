"""A device stores and reads back the engine files of the job it runs (``services/devices/engine_state``), with its
own device token. Anyone else, another device or a job not active on this one is a 404."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import UserDevice
from ....services.data_access import as_viewer
from ....services.devices import engine_state
from ....services.devices.credential import resolve_device_credential
from ....services.devices.runner_pool import RUNNER_SERVICE_KIND
from ....services.devices.runner_tenant import runner_channel_viewer

router = APIRouter(tags=["device-session-state"])
PATH = "/api/v1/devices/jobs/{job_id}/session-state"
_STATUS = {engine_state.REASON_TOO_LARGE: 413, engine_state.REASON_UNAVAILABLE: 503}


def _not_found() -> JSONResponse:
    return JSONResponse({"detail": {"code": "session_state_not_found", "message": "no such job running on this "
                                    "device; instead: continue without it"}}, status_code=404)


async def _device(request: Request, db: AsyncSession) -> UserDevice | None:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    credential = await resolve_device_credential(db, header[7:].strip())
    return None if isinstance(credential, str) else credential.device


async def _viewer(db: AsyncSession, device: UserDevice) -> str | None:
    # A runner's account is a member of nothing: it reads as the person whose turn it holds, like its channel.
    if device.service_kind == RUNNER_SERVICE_KIND:
        return await runner_channel_viewer(db, device.id)
    return device.owner_user_id


async def _body(request: Request) -> bytes | None:
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > engine_state.MAX_STATE_BYTES:
            return None
    return bytes(received)


@router.put(PATH)
async def put_session_state(job_id: str, request: Request, engine: str = Query(..., max_length=20),
                            engine_session_id: str = Query(..., max_length=80),
                            turn_id: str = Query(..., max_length=40), sha256: str = Query(..., max_length=64),
                            size: int = Query(..., alias="bytes", ge=0), db: AsyncSession = Depends(get_db)):
    device = await _device(request, db)
    viewer = await _viewer(db, device) if device is not None else None
    if device is None or viewer is None:
        return _not_found()
    with as_viewer(viewer):
        job = await engine_state.held_job(db, device.id, job_id)
        if job is None:
            return _not_found()
        # Over the cap the body is not read at all; the refusal is recorded all the same.
        data = await _body(request) if size <= engine_state.MAX_STATE_BYTES else b""
        reason = await engine_state.store_snapshot(
            db, job, engine=engine, engine_session_id=engine_session_id, turn_id=turn_id, sha256=sha256,
            size=size if data is not None else engine_state.MAX_STATE_BYTES + 1, data=data or b"")
        await db.commit()
    if reason:
        return JSONResponse({"state": "refused", "reason": reason}, status_code=_STATUS.get(reason, 400))
    return {"state": "stored", "sha256": sha256, "bytes": size}


@router.get(PATH)
async def get_session_state(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    device = await _device(request, db)
    viewer = await _viewer(db, device) if device is not None else None
    if device is None or viewer is None:
        return _not_found()
    with as_viewer(viewer):
        job = await engine_state.held_job(db, device.id, job_id)
        found = await engine_state.load_snapshot(db, job) if job is not None else None
        await db.commit()
    if found is None:
        return _not_found()
    data, digest = found
    return Response(content=data, media_type="application/gzip",
                    headers={"cache-control": "no-store", "x-octryx-sha256": digest})


__all__ = ["router"]
