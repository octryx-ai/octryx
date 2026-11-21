"""Contract: who may use the agent gateway, for which Workspace and which launcher session."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User
from app.models.security.oauth_provider import OAuthGrant
from app.services.agent_gateway.contract import (
    GATEWAY_AUDIENCE,
    REASON_SCOPE_MISSING,
    REASON_SESSION_HEADER_MISSING,
    REASON_SESSION_WORKSPACE_MISMATCH,
    REASON_TOKEN_INVALID,
    REASON_WORKSPACE_NOT_AUTHORIZED,
    REASON_WORKSPACE_NOT_SELECTED,
    SCOPE_MODEL_INVOKE,
)
from app.services.agent_gateway.identity import GatewayIdentity, GatewayRefusal, resolve_gateway_identity
from app.services.agent_gateway.sessions import find_gateway_session, get_or_create_gateway_session
from app.services.oauth_provider import mint_access_token


async def _token(db: AsyncSession, *, scopes: list[str], resource: str | None = GATEWAY_AUDIENCE, project_ids=None):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    grant = OAuthGrant(
        user_id=admin.id, client_id=f"oec_gw_{uuid.uuid4().hex[:6]}", scopes=scopes, project_ids=project_ids
    )
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(
        user_id=admin.id, client_id=grant.client_id, grant_id=grant.id, scopes=scopes, resource=resource
    )
    return token


async def _workspace(db: AsyncSession) -> Project:
    return (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()


def _headers(token: str, *, workspace: str = "", session: str | bool | None = None) -> dict[str, str]:
    headers = {"authorization": f"Bearer {token}"}
    if workspace:
        headers["x-octryx-workspace"] = workspace
    if session is not False:
        headers["x-octryx-session"] = session or str(uuid.uuid4())
    return headers


@pytest.mark.asyncio
async def test_gateway_token_resolves_identity_and_one_shadow_session_per_key(db):
    workspace = await _workspace(db)
    token = await _token(db, scopes=[SCOPE_MODEL_INVOKE])
    key = str(uuid.uuid4())

    identity = await resolve_gateway_identity(db, _headers(token, workspace=workspace.id, session=key))
    assert isinstance(identity, GatewayIdentity)
    assert identity.workspace_id == workspace.id

    first = await get_or_create_gateway_session(db, identity)
    second = await get_or_create_gateway_session(db, identity)
    assert first.id == second.id
    assert first.project_id == workspace.id
    assert first.metadata_["external_source"] == "octryx_claude"
    assert (await find_gateway_session(db, identity)).id == first.id


@pytest.mark.asyncio
async def test_refusals_are_explicit_states(db):
    workspace = await _workspace(db)
    gateway = await _token(db, scopes=[SCOPE_MODEL_INVOKE])

    mcp_audience = await _token(db, scopes=[SCOPE_MODEL_INVOKE], resource=None)
    refusal = await resolve_gateway_identity(db, _headers(mcp_audience, workspace=workspace.id))
    assert refusal == GatewayRefusal("unauthorized", REASON_TOKEN_INVALID)

    no_scope = await _token(db, scopes=["knowledge:read"])
    refusal = await resolve_gateway_identity(db, _headers(no_scope, workspace=workspace.id))
    assert refusal == GatewayRefusal("denied", REASON_SCOPE_MISSING)

    refusal = await resolve_gateway_identity(db, _headers(gateway, workspace=workspace.id, session=False))
    assert refusal == GatewayRefusal("needs_configuration", REASON_SESSION_HEADER_MISSING)

    refusal = await resolve_gateway_identity(db, _headers(gateway))
    assert refusal == GatewayRefusal("needs_configuration", REASON_WORKSPACE_NOT_SELECTED)

    refusal = await resolve_gateway_identity(db, _headers(gateway, workspace=str(uuid.uuid4())))
    assert refusal == GatewayRefusal("denied", REASON_WORKSPACE_NOT_AUTHORIZED)


@pytest.mark.asyncio
async def test_bound_grant_selects_its_single_workspace_and_a_key_cannot_switch_workspace(db):
    workspace = await _workspace(db)
    bound = await _token(db, scopes=[SCOPE_MODEL_INVOKE], project_ids=[workspace.id])
    key = str(uuid.uuid4())
    identity = await resolve_gateway_identity(db, _headers(bound, session=key))
    assert isinstance(identity, GatewayIdentity) and identity.workspace_id == workspace.id
    await get_or_create_gateway_session(db, identity)

    other = (await db.execute(select(Project).where(Project.id != workspace.id).limit(1))).scalar_one_or_none()
    if other is None:
        pytest.skip("baseline seeds a single project")
    moved = GatewayIdentity(
        user=identity.user,
        grant_id=identity.grant_id,
        oauth_client_id=identity.oauth_client_id,
        workspace_id=other.id,
        session_key=key,
        work_item_key="",
    )
    refusal = await get_or_create_gateway_session(db, moved)
    assert refusal == GatewayRefusal("denied", REASON_SESSION_WORKSPACE_MISMATCH)
