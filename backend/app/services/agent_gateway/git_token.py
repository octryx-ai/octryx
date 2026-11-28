"""The run-bound git token: a launcher session's read access to its run's repository (``git_upload``). Each git
request checks grant, turn, membership, session and run again, as the gateway checks a login."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import Session, User, WorkflowRun
from ...models.security.oauth_provider import OAuthGrant
from ...time_utils import utc_now
from ..oauth_provider.resource import OAuthResourceContext
from .contract import STATE_DENIED, STATE_UNAUTHORIZED
from .identity import GatewayIdentity, GatewayRefusal, identity_for_login
from .sessions import find_gateway_session

GIT_AUDIENCE = "octryx-git"
GIT_ISSUER = "octryx-git"
TTL_SECONDS = 600
REASON_GIT_TOKEN_MISSING = "git_token_missing"
REASON_GIT_TOKEN_INVALID = "git_token_invalid"
REASON_GIT_TOKEN_OTHER_RUN = "git_token_other_run"
REASON_GIT_RUN_NOT_ACTIVE = "git_run_not_active"


def mint_git_token(identity: GatewayIdentity, login_user_id: str, run: WorkflowRun) -> tuple[str, int]:
    payload: dict[str, Any] = {
        "sub": login_user_id, "grant": identity.grant_id, "client": identity.oauth_client_id,
        "ws": identity.workspace_id, "sk": identity.session_key, "run": run.id,
        "aud": GIT_AUDIENCE, "iss": GIT_ISSUER, "exp": utc_now() + timedelta(seconds=TTL_SECONDS),
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256"), TTL_SECONDS


def _claims(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], audience=GIT_AUDIENCE,
                          issuer=GIT_ISSUER)
    except jwt.PyJWTError:
        return None


async def _login(db: AsyncSession, claims: dict[str, Any]) -> tuple[User, OAuthResourceContext] | None:
    grant = await db.get(OAuthGrant, str(claims.get("grant") or ""))
    user_id = str(claims.get("sub") or "")
    if grant is None or grant.revoked_at is not None or not user_id or grant.user_id != user_id:
        return None
    user = await db.get(User, user_id)
    if user is None or not bool(getattr(user, "is_active", True)):
        return None
    projects = grant.project_ids
    bound = tuple(str(item) for item in projects) if isinstance(projects, list) and projects else None
    return user, OAuthResourceContext(user_id=user_id, grant_id=grant.id, scopes=(), bound_project_ids=bound,
                                      oauth_client_id=str(claims.get("client") or ""))


async def verify_git_token(db: AsyncSession, token: str, run_id: str
                           ) -> tuple[GatewayIdentity, Session, WorkflowRun] | GatewayRefusal:
    from ..workflow_runs.records import active_run_for_session  # noqa: PLC0415

    if not token:
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_GIT_TOKEN_MISSING)
    claims = _claims(token)
    if claims is None:
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_GIT_TOKEN_INVALID)
    if str(claims.get("run") or "") != run_id:
        return GatewayRefusal(STATE_DENIED, REASON_GIT_TOKEN_OTHER_RUN)
    login = await _login(db, claims)
    if login is None:
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_GIT_TOKEN_INVALID)
    identity = await identity_for_login(db, *login, session_key=str(claims.get("sk") or ""),
                                        workspace=str(claims.get("ws") or ""))
    if isinstance(identity, GatewayRefusal):
        return identity
    session = await find_gateway_session(db, identity)
    if isinstance(session, GatewayRefusal):
        return session
    run = await active_run_for_session(db, session.id)
    if run is None or run.id != run_id or run.project_id != identity.workspace_id:
        return GatewayRefusal(STATE_DENIED, REASON_GIT_RUN_NOT_ACTIVE)
    return identity, session, run


__all__ = [
    "GIT_AUDIENCE",
    "REASON_GIT_RUN_NOT_ACTIVE",
    "REASON_GIT_TOKEN_INVALID",
    "REASON_GIT_TOKEN_MISSING",
    "REASON_GIT_TOKEN_OTHER_RUN",
    "TTL_SECONDS",
    "mint_git_token",
    "verify_git_token",
]
