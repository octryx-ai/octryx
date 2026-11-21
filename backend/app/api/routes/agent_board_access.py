"""Workspace access of the agent board REST: a non-member gets the same 404 as for something that does not exist;
admin actions need admin/owner."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth.tokens import JWT_AUDIENCE, JWT_ISSUER

from ...db import get_db
from ...http_security import API_KEY_HEADER
from ...models import Project, User
from ...services.access_control import get_project_role_for_user, workspace_not_found
from ...services.agent_board.messages import ADMIN_ROLES
from ...services.auth.service import cookie_access_token, get_current_user, security


async def require_member(
    db: AsyncSession, user_id: str, project_id: str, *, admin: bool = False, not_found: str | None = None
) -> str:
    """The caller's Workspace role; 403 when ``admin`` and the role is not admin/owner.

    A caller who is no member learns nothing: a Workspace route answers the shared ``project_not_found`` 404 (the same
    as an unknown Workspace), and an item route passes its own ``not_found`` text, so a foreign item answers exactly
    like one that does not exist. ``get_project_role_for_user`` answers ``admin`` for platform admins even for an id
    that names no Workspace, so the Workspace must exist first.
    """
    exists = bool(project_id) and await db.get(Project, project_id) is not None
    role = await get_project_role_for_user(db, user_id, project_id) if exists else None
    if role is None:
        raise HTTPException(status_code=404, detail=not_found) if not_found else workspace_not_found()
    if admin and role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Workspace admin or owner role required")
    return role


def viewer(user_id: str, role: str) -> dict[str, Any]:
    """What the UI may *offer*; the server still authorizes every action."""
    return {"user_id": user_id, "can_admin": role in ADMIN_ROLES}


_TOKEN_ONLY_CLAIMS = frozenset({"scope", "client_id", "grant_id", "sid"})
CODE_INTERACTIVE_REQUIRED = "interactive_session_required"


async def interactive_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """A person in the UI (platform session JWT or cookie), never a key or a client token.

    ``X-API-Key`` and any token that is not a plain platform session (OAuth gateway/MCP tokens, stream tokens)
    are refused with 403 before anything is read.
    """
    if str(request.headers.get(API_KEY_HEADER) or "").strip():
        raise HTTPException(status_code=403, detail={"code": CODE_INTERACTIVE_REQUIRED})
    token = (credentials.credentials if credentials else "") or cookie_access_token(request)
    if token:
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            claims = {}
        if claims.get("iss") != JWT_ISSUER or claims.get("aud") != JWT_AUDIENCE or _TOKEN_ONLY_CLAIMS & set(claims):
            raise HTTPException(status_code=403, detail={"code": CODE_INTERACTIVE_REQUIRED})
    return await get_current_user(request, credentials, db)


__all__ = ["interactive_user", "require_member", "viewer"]
