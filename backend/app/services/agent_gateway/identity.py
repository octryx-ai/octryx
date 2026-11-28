"""Who is calling the agent gateway, for which Workspace and which launcher session, from the headers alone."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..data_access import bind_request_viewer
from ..oauth_provider.resource import resolve_oauth_resource_context
from ..project import get_user_project_ids
from .contract import (
    GATEWAY_AUDIENCE,
    HEADER_SESSION,
    HEADER_WORK_ITEM,
    HEADER_WORKFLOW_RUN,
    HEADER_WORKSPACE,
    REASON_SCOPE_MISSING,
    REASON_SESSION_HEADER_INVALID,
    REASON_SESSION_HEADER_MISSING,
    REASON_TOKEN_INVALID,
    REASON_TOKEN_MISSING,
    REASON_USER_INACTIVE,
    REASON_WORKSPACE_NOT_AUTHORIZED,
    REASON_WORKSPACE_NOT_SELECTED,
    SCOPE_MODEL_INVOKE,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
    STATE_UNAUTHORIZED,
)

_MAX_WORK_ITEM_CHARS = 120


@dataclass(frozen=True, slots=True)
class GatewayRefusal:
    state: str
    reason: str

    @property
    def http_status(self) -> int:
        if self.state == STATE_UNAUTHORIZED:
            return 401
        if self.state == STATE_DENIED:
            return 403
        return 400


@dataclass(frozen=True, slots=True)
class GatewayIdentity:
    user: User
    grant_id: str
    oauth_client_id: str
    workspace_id: str
    session_key: str
    work_item_key: str
    # The workflow run a device job carries (``X-Octryx-Workflow-Run``); bound only after the checks.
    workflow_run_id: str = ""


def bearer_token(headers: Mapping[str, str]) -> str:
    authorization = str(headers.get("authorization") or "").strip()
    # Claude Code's ``apiKeyHelper`` value arrives in both headers; either suffices.
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(headers.get("x-api-key") or "").strip()


def _session_key(headers: Mapping[str, str]) -> tuple[str, str]:
    raw = str(headers.get(HEADER_SESSION) or "").strip()
    if not raw:
        return "", REASON_SESSION_HEADER_MISSING
    try:
        return str(uuid.UUID(raw)), ""
    except ValueError:
        return "", REASON_SESSION_HEADER_INVALID


async def _resolve_workspace(
    db: AsyncSession,
    *,
    user_id: str,
    requested: str,
    bound_project_ids: tuple[str, ...] | None,
) -> tuple[str, GatewayRefusal | None]:
    if not requested:
        if bound_project_ids is not None and len(bound_project_ids) == 1:
            requested = bound_project_ids[0]
        else:
            return "", GatewayRefusal(STATE_NEEDS_CONFIGURATION, REASON_WORKSPACE_NOT_SELECTED)
    if bound_project_ids is not None and requested not in bound_project_ids:
        return "", GatewayRefusal(STATE_DENIED, REASON_WORKSPACE_NOT_AUTHORIZED)
    # A grant may be unbound: membership is checked on every call, so a removed member loses access at once.
    if requested not in set(await get_user_project_ids(user_id, db)):
        return "", GatewayRefusal(STATE_DENIED, REASON_WORKSPACE_NOT_AUTHORIZED)
    return requested, None


async def resolve_gateway_login(db: AsyncSession, headers: Mapping[str, str]) -> tuple[User, Any] | GatewayRefusal:
    token = bearer_token(headers)
    if not token:
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_TOKEN_MISSING)
    context = await resolve_oauth_resource_context(db, token=token, audiences={GATEWAY_AUDIENCE})
    if context is None:
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_TOKEN_INVALID)
    if not context.has_scope(SCOPE_MODEL_INVOKE):
        return GatewayRefusal(STATE_DENIED, REASON_SCOPE_MISSING)
    user = await db.get(User, context.user_id)
    if user is None or not bool(getattr(user, "is_active", True)):
        return GatewayRefusal(STATE_UNAUTHORIZED, REASON_USER_INACTIVE)
    bind_request_viewer(user.id)  # the gateway's principal, like the private-Workspace gate's on other routes
    return user, context


async def _acting_user(db: AsyncSession, user: User, context: Any, requested: str, session_key: str = "") -> User:
    from ..devices.runner_identity import is_runner_account, runner_turn_owner  # noqa: PLC0415

    if not is_runner_account(user):
        return user
    owner = await runner_turn_owner(db, user, grant_id=context.grant_id, workspace_id=requested,
                                    session_key=session_key)
    if owner is None:
        return user  # without a turn the runner account is a member of nothing and is refused below
    bind_request_viewer(owner.id)  # the rest of the request reads as the turn's owner, like a device as its owner
    return owner


async def authorize_login_workspace(
    db: AsyncSession, user: User, context: Any, requested: str
) -> tuple[str, GatewayRefusal | None]:
    # Only a member Workspace inside the grant's binding; anything else is a fixed refusal.
    acting = await _acting_user(db, user, context, requested.strip())
    return await _resolve_workspace(
        db, user_id=acting.id, requested=requested.strip(), bound_project_ids=context.bound_project_ids
    )


async def resolve_gateway_identity(
    db: AsyncSession,
    headers: Mapping[str, str],
) -> GatewayIdentity | GatewayRefusal:
    login = await resolve_gateway_login(db, headers)
    if isinstance(login, GatewayRefusal):
        return login
    user, context = login
    session_key, session_reason = _session_key(headers)
    if session_reason:
        return GatewayRefusal(STATE_NEEDS_CONFIGURATION, session_reason)
    return await identity_for_login(
        db, user, context, session_key=session_key, workspace=str(headers.get(HEADER_WORKSPACE) or ""),
        work_item=str(headers.get(HEADER_WORK_ITEM) or ""), workflow_run=str(headers.get(HEADER_WORKFLOW_RUN) or ""),
    )


async def identity_for_login(
    db: AsyncSession, user: User, context: Any, *, session_key: str, workspace: str, work_item: str = "",
    workflow_run: str = "",
) -> GatewayIdentity | GatewayRefusal:
    requested = workspace.strip()
    user = await _acting_user(db, user, context, requested, session_key)
    workspace_id, refusal = await _resolve_workspace(
        db,
        user_id=user.id,
        requested=requested,
        bound_project_ids=context.bound_project_ids,
    )
    if refusal is not None:
        return refusal
    return GatewayIdentity(
        user=user,
        grant_id=context.grant_id,
        oauth_client_id=context.oauth_client_id,
        workspace_id=workspace_id,
        session_key=session_key,
        work_item_key=work_item.strip()[:_MAX_WORK_ITEM_CHARS],
        workflow_run_id=workflow_run.strip()[:36],
    )


__all__ = [
    "GatewayIdentity",
    "GatewayRefusal",
    "authorize_login_workspace",
    "bearer_token",
    "identity_for_login",
    "resolve_gateway_identity",
    "resolve_gateway_login",
]
