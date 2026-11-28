"""Agent gateway: the launcher's repository binding and local snapshot upload."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.sources.repository_snapshot.snapshot_complete import complete_snapshot_pass
from app.services.knowledge.sources.repository_snapshot.snapshot_files import max_batch_bytes, upload_snapshot_files

from ....db import get_db
from ....services.agent_gateway.contract import STATE_DENIED
from ....services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity
from ....services.agent_gateway.repository_root import binding_refusal
from ....services.agent_gateway.sessions import find_gateway_session, get_or_create_gateway_session
from ....services.knowledge.sources.repository_snapshot.binding import SnapshotRefusal, bind_session_repository
from ....services.knowledge.sources.repository_snapshot.upload import open_snapshot_pass
from ._agent_gateway_http import _bounded_json, _from_refusal, _refusal

router = APIRouter(prefix="/api/v1/agent-gateway/sessions/repository", tags=["agent-gateway"])

MAX_BINDING_BODY_BYTES = 16 * 1024
MAX_MANIFEST_BODY_BYTES = 4 * 1024 * 1024
# 3 MiB of raw content per batch is 4 MiB as base64, plus the JSON envelope.
MAX_FILES_BODY_BYTES = 5 * 1024 * 1024


def files_body_limit() -> int:
    return max(MAX_FILES_BODY_BYTES, max_batch_bytes() * 4 // 3 + 64 * 1024)
MAX_COMPLETE_BODY_BYTES = 4 * 1024


def _snapshot_refusal(refusal: SnapshotRefusal) -> JSONResponse:
    return _refusal(refusal.state, refusal.reason, 403 if refusal.state == STATE_DENIED else 409)


async def _body(request: Request, limit: int) -> dict[str, Any] | JSONResponse:
    body = await _bounded_json(request, limit)
    if isinstance(body, tuple):
        return _refusal(STATE_DENIED, *body)
    return body


def _answer(result: dict[str, Any] | SnapshotRefusal) -> dict[str, Any] | JSONResponse:
    return _snapshot_refusal(result) if isinstance(result, SnapshotRefusal) else result


@router.post("")
async def bind_repository(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    body = await _body(request, MAX_BINDING_BODY_BYTES)
    if isinstance(body, JSONResponse):
        return body
    session = await get_or_create_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    result = await binding_refusal(db, session=session, grant_id=identity.grant_id, user_id=identity.user.id,
                                   payload=body) or await bind_session_repository(
        db, session=session, user_id=identity.user.id, workspace_id=identity.workspace_id, payload=body
    )
    if not isinstance(result, SnapshotRefusal):
        await db.commit()
    return _answer(result)


async def _pass_call(request: Request, db: AsyncSession, limit: int, operation) -> dict[str, Any] | JSONResponse:
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _from_refusal(identity)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _from_refusal(session)
    body = await _body(request, limit)
    if isinstance(body, JSONResponse):
        return body
    result = await operation(db, session=session, identity=identity, payload=body)
    if not isinstance(result, SnapshotRefusal):
        await db.commit()
    return _answer(result)


@router.post("/manifest")
async def snapshot_manifest(request: Request, db: AsyncSession = Depends(get_db)):
    async def operation(db, *, session, identity, payload):
        return await open_snapshot_pass(
            db, session=session, workspace_id=identity.workspace_id, user_id=identity.user.id, payload=payload
        )

    return await _pass_call(request, db, MAX_MANIFEST_BODY_BYTES, operation)


@router.post("/files")
async def snapshot_files(request: Request, db: AsyncSession = Depends(get_db)):
    async def operation(db, *, session, identity, payload):
        return await upload_snapshot_files(
            db, session=session, workspace_id=identity.workspace_id, user_id=identity.user.id, payload=payload
        )

    return await _pass_call(request, db, files_body_limit(), operation)


@router.post("/complete")
async def snapshot_complete(request: Request, db: AsyncSession = Depends(get_db)):
    async def operation(db, *, session, identity, payload):
        return await complete_snapshot_pass(
            db, session=session, workspace_id=identity.workspace_id, user_id=identity.user.id, payload=payload
        )

    return await _pass_call(request, db, MAX_COMPLETE_BODY_BYTES, operation)
