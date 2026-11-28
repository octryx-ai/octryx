"""``POST /api/v1/devices/runner/enroll``: a server runner joins the platform's pool with the installation's join
secret (``runner_pool``) and gets an ordinary device credential."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import get_settings
from ....db import get_db
from ....services.devices.contract import DEVICE_AUDIENCE
from ....services.devices.registry_values import DeviceRegistryError
from ....services.devices.registry_view import serialize_device
from ....services.devices.runner_pool import RunnerEnrollError, enroll_runner

router = APIRouter(tags=["devices"])


@router.post("/api/v1/devices/runner/enroll")
async def enroll(body: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    client_id = str(body.get("client_id") or "")
    settings = get_settings()
    try:
        registration = await enroll_runner(db, join_secret=str(body.get("join_secret") or ""),
                                           configured_secret=settings.runner_join_secret, client_id=client_id,
                                           body={key: body[key] for key in ("name", "public_key", "client_version",
                                                                            "max_parallel_jobs") if key in body},
                                           runtime=str(body.get("runtime") or ""),
                                           required_runtime=settings.runner_runtime)
    except RunnerEnrollError as error:
        return JSONResponse({"state": "denied", "reason": error.reason}, status_code=error.status)
    except DeviceRegistryError as error:
        return JSONResponse({"state": "denied", "reason": error.reason}, status_code=422)
    await db.commit()
    return JSONResponse(
        {"state": "registered", "device": serialize_device(registration.device, owner_view=True),
         "credential": {"refresh_token": registration.refresh_token, "client_id": client_id,
                        "scopes": list(registration.scopes), "audience": DEVICE_AUDIENCE}},
        status_code=201, headers={"cache-control": "no-store"})
