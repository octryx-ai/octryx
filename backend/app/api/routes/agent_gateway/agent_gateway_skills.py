"""Catalog skills for octryx-claude: the session manifest, its blobs and slash-command usage."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....services.agent_gateway.contract import HEADER_GATEWAY_REASON, HEADER_GATEWAY_STATE, STATE_DENIED
from ....services.agent_gateway.identity import GatewayRefusal, resolve_gateway_identity
from ....services.agent_gateway.sessions import find_gateway_session
from ....services.api_key.service import get_user_role_names
from ....services.skill_catalog.bundle import load_blob
from ....services.skill_catalog.delivery import build_manifest, manifest_blobs
from ....services.skill_catalog.usage import INVOCATION_SLASH, record_claude_use, skill_reference

router = APIRouter()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_SKILL_USED_BYTES = 4096


def _refused(state: str, reason: str, status: int) -> JSONResponse:
    return JSONResponse({"state": state, "reason": reason}, status_code=status,
                        headers={HEADER_GATEWAY_STATE: state, HEADER_GATEWAY_REASON: reason})


async def _manifest(request: Request, db: AsyncSession):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return identity, None
    roles = sorted(await get_user_role_names(db, identity.user.id))
    return identity, await build_manifest(db, project_id=identity.workspace_id, user_roles=roles)


@router.get("/skills/manifest")
async def skills_manifest(request: Request, db: AsyncSession = Depends(get_db)):
    identity, manifest = await _manifest(request, db)
    if isinstance(identity, GatewayRefusal):
        return _refused(identity.state, identity.reason, identity.http_status)
    await db.commit()  # the rebuilt SKILL.md files are stored as blobs
    return {"state": "allowed", **manifest}


@router.get("/skills/blobs/{sha256}")
async def skills_blob(sha256: str, request: Request, db: AsyncSession = Depends(get_db)):
    if not _SHA256.match(sha256):
        return _refused(STATE_DENIED, "skill_blob_invalid", 400)
    identity, manifest = await _manifest(request, db)
    if isinstance(identity, GatewayRefusal):
        return _refused(identity.state, identity.reason, identity.http_status)
    if sha256 not in manifest_blobs(manifest):
        return _refused(STATE_DENIED, "skill_blob_not_in_manifest", 404)
    blob = await load_blob(db, sha256)
    if blob is None:
        return _refused(STATE_DENIED, "skill_blob_missing", 404)
    await db.commit()
    return {"state": "allowed", "sha256": blob.sha256, "content": blob.content}


@router.post("/sessions/skill-used")
async def skill_used(request: Request, db: AsyncSession = Depends(get_db)):
    identity = await resolve_gateway_identity(db, request.headers)
    if isinstance(identity, GatewayRefusal):
        return _refused(identity.state, identity.reason, identity.http_status)
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return _refused(session.state, session.reason, session.http_status)
    raw = await request.body()
    if len(raw) > MAX_SKILL_USED_BYTES:
        return _refused(STATE_DENIED, "body_too_large", 413)
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return _refused(STATE_DENIED, "body_invalid", 400)
    body = body if isinstance(body, dict) else {}
    reference = skill_reference({"skill": body.get("command_name")})
    event = await record_claude_use(db, reference=reference, invocation=INVOCATION_SLASH, user_id=identity.user.id,
                                    project_id=identity.workspace_id, session_id=session.id,
                                    source=str(body.get("command_source") or ""))
    await db.commit()
    return {"state": "recorded" if event is not None else "ignored",
            "managed": bool(event is not None and event.skill_id)}
