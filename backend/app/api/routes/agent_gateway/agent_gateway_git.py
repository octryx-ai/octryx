"""Agent gateway: a session's run repository over git smart HTTP, read-only, with a run-bound token
(``POST sessions/git-token``). A push is refused: the platform pushes the reviewed change (``scm.push``)."""

from __future__ import annotations

import base64
import binascii
import zlib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.agent_gateway import git_upload
from ....services.agent_gateway.contract import (
    HEADER_SESSION,
    HEADER_WORKSPACE,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
    STATE_UNAUTHORIZED,
)
from ....services.agent_gateway.git_token import mint_git_token, verify_git_token
from ....services.agent_gateway.identity import GatewayRefusal, identity_for_login, resolve_gateway_login
from ....services.agent_gateway.sessions import find_gateway_session
from ....services.workflow_runs.records import active_run_for_session
from ....services.workflow_runs.workspace.gateway import REASON_NO_RUN
from ._agent_gateway_http import _from_refusal, _refusal

router = APIRouter(prefix="/api/v1/agent-gateway", tags=["agent-gateway"])

GIT_USERNAME = "octryx-run"
REASON_PUSH_REFUSED = "git_push_through_platform"
REASON_SERVICE_UNSUPPORTED = "git_service_unsupported"
REASON_BODY_TOO_LARGE = "request_body_too_large"
REASON_BODY_INVALID = "request_body_invalid"
# What a fetch sends (its wants and haves) is small next to what it receives; the bound keeps the body finite.
MAX_UPLOAD_REQUEST_BYTES = 32 * 1024 * 1024
_REALM = {"WWW-Authenticate": 'Basic realm="Octryx run repository"'}


@router.post("/sessions/git-token")
async def git_token(request: Request, db: AsyncSession = Depends(get_db)):
    login = await resolve_gateway_login(db, request.headers)
    if isinstance(login, GatewayRefusal):
        return _from_refusal(login)
    user, context = login
    identity = await identity_for_login(db, user, context, session_key=str(request.headers.get(HEADER_SESSION) or ""),
                                        workspace=str(request.headers.get(HEADER_WORKSPACE) or ""))
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    run = await active_run_for_session(db, session.id)
    if run is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, REASON_NO_RUN, 409)
    root, problem = git_upload.working_copy(run)
    if root is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, problem, 409)
    token, expires_in = mint_git_token(identity, user.id, run)
    return {"state": "ready", "username": GIT_USERNAME, "token": token, "expires_in": expires_in,
            "path": git_upload.git_path(run.id), "branch": run.branch}


def _token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "").strip()
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer":
        return value.strip()
    if scheme.lower() == "basic":
        try:
            return base64.b64decode(value.strip(), validate=True).decode().partition(":")[2]
        except (binascii.Error, UnicodeDecodeError):
            return ""
    return ""


async def _authorized(request: Request, db: AsyncSession, run_id: str):
    verified = await verify_git_token(db, _token(request), run_id)
    if isinstance(verified, GatewayRefusal):
        response = _from_refusal(verified)
        if verified.state == STATE_UNAUTHORIZED:
            response.headers.update(_REALM)
        return response
    _identity, _session, run = verified
    root, problem = git_upload.working_copy(run)
    if root is None:
        return _refusal(STATE_NEEDS_CONFIGURATION, problem, 409)
    return root, str(run.branch)


async def _request_body(request: Request) -> bytes | None:
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > MAX_UPLOAD_REQUEST_BYTES:
            return None
    if request.headers.get("content-encoding", "").lower() != "gzip":
        return bytes(received)
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        data = inflater.decompress(bytes(received), MAX_UPLOAD_REQUEST_BYTES + 1)
    except zlib.error:
        return b""
    return None if len(data) > MAX_UPLOAD_REQUEST_BYTES or inflater.unconsumed_tail else data


@router.get("/git/{run_id}/info/refs")
async def git_refs(run_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    service = request.query_params.get("service") or ""
    if service == "git-receive-pack":
        return _refusal(STATE_DENIED, REASON_PUSH_REFUSED, 403)
    if service != git_upload.SERVICE:
        return _refusal(STATE_DENIED, REASON_SERVICE_UNSUPPORTED, 403)
    authorized = await _authorized(request, db, run_id)
    if isinstance(authorized, JSONResponse):
        return authorized
    root, branch = authorized
    return StreamingResponse(git_upload.advertisement(root, branch), media_type=git_upload.ADVERTISEMENT_TYPE,
                             headers={"Cache-Control": "no-cache"})


@router.post("/git/{run_id}/git-upload-pack")
async def git_upload_pack(run_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    authorized = await _authorized(request, db, run_id)
    if isinstance(authorized, JSONResponse):
        return authorized
    root, branch = authorized
    body = await _request_body(request)
    if body is None:
        return _refusal(STATE_DENIED, REASON_BODY_TOO_LARGE, 413)
    if not body:
        return _refusal(STATE_DENIED, REASON_BODY_INVALID, 400)
    return StreamingResponse(git_upload.upload_pack(root, branch, body), media_type=git_upload.RESULT_TYPE,
                             headers={"Cache-Control": "no-cache"})


@router.post("/git/{run_id}/git-receive-pack")
async def git_receive_pack(run_id: str):
    return _refusal(STATE_DENIED, REASON_PUSH_REFUSED, 403)


__all__ = ["GIT_USERNAME", "router"]
