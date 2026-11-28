"""OAuth 2.1 authorization-server endpoints (metadata, register, token, revoke)."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....http_multipart_route import SelfAuthenticatedFormRoute
from ....models.security.oauth_provider import OAuthClient
from ....services.auth_rate_limit import get_auth_rate_limit_state, register_auth_failure
from ....services.oauth_provider import (
    OAuthClientRegistrationError,
    OAuthFlowError,
    authorization_server_metadata,
    exchange_authorization_code,
    get_active_client,
    refresh_with_token,
    register_client,
    revoke_token,
    verify_client_secret,
)
from ....services.oauth_provider.resource_indicators import resolve_resource_indicator

router = APIRouter(tags=["oauth-provider"], route_class=SelfAuthenticatedFormRoute)

OAUTH_REGISTER_SCOPE = "oauth_register"
OAUTH_TOKEN_SCOPE = "oauth_token"


def _issuer(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _error(status_code: int, error: str, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "error_description": description},
    )


def _rate_limited(scope: str, request: Request) -> JSONResponse | None:
    state = get_auth_rate_limit_state(scope, request)
    if state.limited:
        return _error(429, "slow_down", "Too many requests; retry later")
    return None


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata(request: Request) -> dict:
    return authorization_server_metadata(_issuer(request))


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata(request: Request) -> dict:
    from ....services.mcp_knowledge_protocol import KNOWLEDGE_MCP_MOUNT_PATH, KNOWLEDGE_MCP_STREAMABLE_PATH
    from ....services.oauth_provider import protected_resource_metadata

    issuer = _issuer(request)
    resource_url = f"{issuer}{KNOWLEDGE_MCP_MOUNT_PATH}{KNOWLEDGE_MCP_STREAMABLE_PATH}"
    return protected_resource_metadata(issuer, resource_url=resource_url)


@router.get("/.well-known/oauth-protected-resource/{resource_path:path}")
async def oauth_protected_resource_metadata_for_path(resource_path: str, request: Request) -> dict:
    """RFC 9728 path-suffixed protected resource metadata. A spec-compliant MCP client follows the challenge to this
    path, so it must resolve for the knowledge MCP endpoint."""
    from fastapi import HTTPException

    from ....services.mcp_knowledge_protocol import KNOWLEDGE_MCP_MOUNT_PATH, KNOWLEDGE_MCP_STREAMABLE_PATH
    from ....services.oauth_provider import protected_resource_metadata

    expected = f"{KNOWLEDGE_MCP_MOUNT_PATH}{KNOWLEDGE_MCP_STREAMABLE_PATH}".strip("/")
    if resource_path.strip("/") != expected:
        raise HTTPException(status_code=404, detail="Unknown protected resource")
    issuer = _issuer(request)
    resource_url = f"{issuer}{KNOWLEDGE_MCP_MOUNT_PATH}{KNOWLEDGE_MCP_STREAMABLE_PATH}"
    return protected_resource_metadata(issuer, resource_url=resource_url)


@router.post("/oauth/register", status_code=201)
async def oauth_register(request: Request, db: AsyncSession = Depends(get_db)):
    blocked = _rate_limited(OAUTH_REGISTER_SCOPE, request)
    if blocked is not None:
        return blocked
    try:
        payload = await request.json()
    except Exception:
        register_auth_failure(OAUTH_REGISTER_SCOPE, request)
        return _error(400, "invalid_client_metadata", "Request body must be JSON")
    if not isinstance(payload, dict):
        register_auth_failure(OAUTH_REGISTER_SCOPE, request)
        return _error(400, "invalid_client_metadata", "Request body must be a JSON object")
    try:
        return await register_client(db, payload=payload)
    except OAuthClientRegistrationError as exc:
        register_auth_failure(OAUTH_REGISTER_SCOPE, request)
        return _error(400, "invalid_client_metadata", str(exc))


async def _authenticate_client(
    request: Request,
    db: AsyncSession,
    *,
    form_client_id: str | None,
    form_client_secret: str | None,
) -> OAuthClient:
    client_id = form_client_id
    client_secret = form_client_secret
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:]).decode("utf-8")
            basic_id, _, basic_secret = decoded.partition(":")
            client_id = client_id or basic_id
            client_secret = client_secret or basic_secret
        except Exception as exc:
            raise OAuthFlowError("invalid_client", "Malformed Basic authorization header") from exc
    if not client_id:
        raise OAuthFlowError("invalid_client", "client_id is required")
    client = await get_active_client(db, client_id)
    if client is None:
        raise OAuthFlowError("invalid_client", "Unknown client")
    if not verify_client_secret(client, client_secret):
        raise OAuthFlowError("invalid_client", "Client authentication failed")
    return client


@router.post("/oauth/token")
async def oauth_token(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(default=None),
    redirect_uri: str | None = Form(default=None),
    code_verifier: str | None = Form(default=None),
    refresh_token: str | None = Form(default=None),
    client_id: str | None = Form(default=None),
    client_secret: str | None = Form(default=None),
    resource: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    blocked = _rate_limited(OAUTH_TOKEN_SCOPE, request)
    if blocked is not None:
        return blocked
    try:
        client = await _authenticate_client(
            request, db, form_client_id=client_id, form_client_secret=client_secret
        )
        audience = resolve_resource_indicator(resource, issuer=_issuer(request))
        if grant_type == "authorization_code":
            if not code or not redirect_uri or not code_verifier:
                raise OAuthFlowError(
                    "invalid_request", "code, redirect_uri and code_verifier are required"
                )
            return await exchange_authorization_code(
                db,
                client=client,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
                resource=audience,
            )
        if grant_type == "refresh_token":
            if not refresh_token:
                raise OAuthFlowError("invalid_request", "refresh_token is required")
            return await refresh_with_token(
                db, client=client, refresh_token=refresh_token, resource=audience
            )
        raise OAuthFlowError("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")
    except OAuthFlowError as exc:
        register_auth_failure(OAUTH_TOKEN_SCOPE, request)
        status_code = 401 if exc.error == "invalid_client" else 400
        return _error(status_code, exc.error, exc.description)


@router.post("/oauth/revoke")
async def oauth_revoke(
    request: Request,
    token: str = Form(...),
    client_id: str | None = Form(default=None),
    client_secret: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        client = await _authenticate_client(
            request, db, form_client_id=client_id, form_client_secret=client_secret
        )
    except OAuthFlowError as exc:
        return _error(401, exc.error, exc.description)
    await revoke_token(db, client=client, token=token)
    # RFC 7009: always 200, even for unknown tokens.
    return JSONResponse({"ok": True})
