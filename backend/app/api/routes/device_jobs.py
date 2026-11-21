"""Device jobs in the chat: read a thread's device job, answer its approvals, stop it.

Transport only; the rules live in ``services/devices/jobs``. Only the job's owner reads, stops or decides; another
user (an admin too) gets ``device_job_not_found`` / ``device_approval_not_owner``.

- ``GET /api/v1/device-jobs?session_id=&after=`` — the thread's jobs with their events after ``after`` and their
  approvals (the chat renders the stream from it and from ``device_job_event`` on the session WebSocket).
- ``POST /api/v1/device-jobs/{job_id}/approvals/{approval_id}`` ``{decision: allow_once|allow_job_edits|deny}``.
- ``POST /api/v1/device-jobs/{job_id}/stop`` — interrupt the running turn on the device.
- ``POST /api/v1/device-jobs/{job_id}/files`` ``{path}`` → 202 ``{file}``: fetch a file the job listed from the
  device (``services/devices/job_files``); ``GET …/files/{file_id}`` → ``{file}`` (its state);
  ``GET …/files/{file_id}/content`` → the bytes. Only the owner's own web or phone login (no API key, no bearer
  token: the file comes from their Mac). Served so it never runs as a page on the platform: pictures inline, text as
  ``text/plain``, everything else as a download; always ``nosniff`` and a sandboxing CSP.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.devices.job_approvals import decide_approval
from app.services.devices.job_state import DeviceJobError, serialize_approval, serialize_job

from ...db import get_db
from ...models import DeviceJob, DeviceJobApproval, DeviceJobEvent, User, UserDevice
from ...services.auth import get_current_user
from ...services.devices.job_files import JobFileError, file_for_owner, request_file, serialize_file
from ...services.devices.job_recovery import fail_stalled_turns
from ...services.devices.jobs import mark_lost_jobs, owned_job, request_stop
from ...services.devices.jobs_channel import publish

router = APIRouter(tags=["devices"])
MAX_EVENTS = 2000


def _refusal(error: DeviceJobError) -> JSONResponse:
    return JSONResponse({"state": error.state, "reason": error.reason}, status_code=error.status)


@router.get("/api/v1/device-jobs")
async def thread_device_jobs(
    session_id: str = Query(..., min_length=1, max_length=36),
    after: int = Query(0, ge=0),
    # "job_id:seq,…" the caller already has; those jobs answer only newer events
    # (``partial``), every other job in full. A job's seq is its own, so one global ``after`` cannot do this.
    known: str = Query("", max_length=2000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    have = _known_seqs(known)
    await mark_lost_jobs(db)
    await fail_stalled_turns(db)
    await db.commit()
    jobs = list((await db.execute(
        select(DeviceJob).where(DeviceJob.session_id == session_id, DeviceJob.owner_user_id == current_user.id)
        .order_by(DeviceJob.created_at)
    )).scalars().all())
    items: list[dict[str, Any]] = []
    for job in jobs:
        device = await db.get(UserDevice, job.device_id)
        since = have.get(job.id, after)
        events = (await db.execute(
            select(DeviceJobEvent).where(DeviceJobEvent.job_id == job.id, DeviceJobEvent.seq > since)
            .order_by(DeviceJobEvent.seq).limit(MAX_EVENTS)
        )).scalars().all()
        approvals = (await db.execute(
            select(DeviceJobApproval).where(DeviceJobApproval.job_id == job.id).order_by(DeviceJobApproval.created_at)
        )).scalars().all()
        items.append({
            **serialize_job(job, device_name=device.name if device else ""),
            "events": [{"seq": event.seq, "type": event.type, "body": event.body} for event in events],
            "approvals": [serialize_approval(approval) for approval in approvals],
            **({"partial": True, "since": since} if job.id in have else {}),
        })
    return {"items": items}


def _known_seqs(raw: str) -> dict[str, int]:
    """``"dj_a:12,dj_b:3"`` → ``{"dj_a": 12, "dj_b": 3}``; malformed parts are ignored (that job comes in full)."""
    have: dict[str, int] = {}
    for part in raw.split(",")[:50]:
        job_id, _, seq = part.strip().partition(":")
        if job_id and len(job_id) <= 40 and seq.isdigit() and len(seq) <= 9:
            have[job_id] = int(seq)
    return have


@router.post("/api/v1/device-jobs/{job_id}/approvals/{approval_id}")
async def decide_device_approval(
    job_id: str,
    approval_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(DeviceJob, job_id)
    local_bearer = target is not None and str(target.profile or "").startswith("local:") and bool(
        request.headers.get("authorization"))
    if getattr(request.state, "api_key_id", None) or local_bearer:
        # An approval lets a tool run on the person's machine: only their own web or phone login decides it, never an
        # API key (a leaked CI or MCP key must not approve a shell command on the Mac), and for a take-over of a
        # session outside octryx no bearer token either.
        return JSONResponse({"state": "denied", "reason": "interactive_login_required"}, status_code=403)
    try:
        approval = await decide_approval(db, job_id=job_id, approval_id=approval_id, user_id=current_user.id,
                                         decision=body.get("decision"))
    except DeviceJobError as error:
        await db.commit()  # an expiry found here is kept
        return _refusal(error)
    await db.commit()
    job = await db.get(DeviceJob, job_id)
    await publish(job, {"eventType": "approval_decided", "approval": serialize_approval(approval)})
    return serialize_approval(approval)


@router.post("/api/v1/device-jobs/{job_id}/stop")
async def stop_device_job(job_id: str, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    try:
        job = await owned_job(db, job_id=job_id, user_id=current_user.id)
        await request_stop(db, job, actor_id=current_user.id)
    except DeviceJobError as error:
        return _refusal(error)
    await db.commit()
    await publish(job, {"eventType": "stop_requested"})
    return serialize_job(job)


_IMAGES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
_TEXT = frozenset({"txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "toml", "log", "py", "ts", "tsx",
                   "js", "jsx", "java", "kt", "go", "rs", "rb", "sh", "sql", "xml", "html", "htm", "svg", "css",
                   "ini", "cfg", "conf", "env.example", "diff", "patch"})


def _interactive_refusal(request: Request) -> JSONResponse | None:
    if getattr(request.state, "api_key_id", None) or request.headers.get("authorization"):
        return JSONResponse({"state": "denied", "reason": "interactive_login_required"}, status_code=403)
    return None


def _file_refusal(error: JobFileError) -> JSONResponse:
    return JSONResponse({"state": "denied", "reason": error.reason}, status_code=error.status)


@router.post("/api/v1/device-jobs/{job_id}/files")
async def fetch_device_file(job_id: str, request: Request, body: dict[str, Any] = Body(...),
                            current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if refusal := _interactive_refusal(request):
        return refusal
    try:
        row = await request_file(db, job_id=job_id, user_id=current_user.id, path=body.get("path"))
    except JobFileError as error:
        await db.commit()  # a purge of expired files is kept
        return _file_refusal(error)
    await db.commit()
    return JSONResponse({"file": serialize_file(row)}, status_code=202)


@router.get("/api/v1/device-jobs/{job_id}/files/{file_id}")
async def device_file_state(job_id: str, file_id: str, request: Request,
                            current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if refusal := _interactive_refusal(request):
        return refusal
    try:
        row = await file_for_owner(db, job_id=job_id, file_id=file_id, user_id=current_user.id)
    except JobFileError as error:
        return _file_refusal(error)
    return {"file": serialize_file(row)}


@router.get("/api/v1/device-jobs/{job_id}/files/{file_id}/content")
async def device_file_content(job_id: str, file_id: str, request: Request, download: bool = Query(False),
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if refusal := _interactive_refusal(request):
        return refusal
    try:
        row = await file_for_owner(db, job_id=job_id, file_id=file_id, user_id=current_user.id)
    except JobFileError as error:
        return _file_refusal(error)
    if row.state != "ready" or row.content is None:
        return JSONResponse({"state": "denied", "reason": "file_not_ready"}, status_code=409)
    name = row.path.rsplit("/", 1)[-1]
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:120] or "file"
    if not download and extension in _IMAGES and extension != "svg":
        media_type, disposition = _IMAGES[extension], "inline"
    elif not download and extension in _TEXT:
        media_type, disposition = "text/plain; charset=utf-8", "inline"
    else:
        media_type, disposition = "application/octet-stream", "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{safe_name}"', "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "sandbox; default-src 'none'", "Cache-Control": "private, no-store"}
    return Response(content=row.content, media_type=media_type, headers=headers)
