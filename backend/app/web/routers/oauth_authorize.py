"""Interactive OAuth authorization endpoint (login-gated consent).

GET /oauth/authorize validates the request, requires an active platform
login (cookie), and either reuses an existing grant or renders the consent
page. POST /oauth/authorize/decision processes the consent form. Invalid
client/redirect_uri combinations render an error page and never redirect
(RFC 6749 §4.1.2.1 open-redirect protection).
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import RefreshToken
from ...services.oauth_provider import (
    create_grant,
    find_reusable_grant,
    get_active_client,
    issue_authorization_code,
    redirect_uri_registered,
)
from ...services.oauth_provider.clients import OAuthClientRegistrationError, _normalize_scopes
from ...services.oauth_provider.flows import OAuthFlowError
from ...services.oauth_provider.resource_indicators import resolve_resource_indicator
from ...time_utils import utc_now
from .._context import templates
from .._helpers.auth import _get_user_from_cookie, validate_browser_origin_headers

router = APIRouter(tags=["oauth-authorize"])


def _error_page(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "oauth_consent.html",
        {"error_message": message, "client_name": None},
        status_code=status_code,
    )


def _redirect_with(redirect_uri: str, params: dict[str, str]) -> RedirectResponse:
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{separator}{urlencode(params)}", status_code=302)


async def _newest_login_session_id(db: AsyncSession, user_id: str) -> str | None:
    """The user's most recent live platform refresh-token row anchors the grant."""
    row = (
        await db.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                # Column is timestamp-without-tz: compare with naive UTC
                # (aware values make asyncpg raise on Postgres).
                RefreshToken.expires_at > utc_now(),
            )
            .order_by(RefreshToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row.id if row is not None else None


async def _validated_request(
    request: Request,
    db: AsyncSession,
    *,
    client_id: str | None,
    redirect_uri: str | None,
    response_type: str | None,
    scope: str | None,
    code_challenge: str | None,
    code_challenge_method: str | None,
):
    """Return (client, scopes, error_response). Never redirects on client errors."""
    if not client_id or not redirect_uri:
        return None, [], _error_page(request, "Missing client_id or redirect_uri.")
    client = await get_active_client(db, client_id)
    if client is None:
        return None, [], _error_page(request, "Unknown or inactive OAuth client.")
    if not redirect_uri_registered(client, redirect_uri):
        return None, [], _error_page(request, "redirect_uri is not registered for this client.")
    if response_type != "code":
        return client, [], _redirect_with(
            redirect_uri, {"error": "unsupported_response_type"}
        )
    if not code_challenge or code_challenge_method != "S256":
        return client, [], _redirect_with(
            redirect_uri,
            {"error": "invalid_request", "error_description": "PKCE S256 code_challenge required"},
        )
    try:
        scopes = _normalize_scopes(scope or "")
    except OAuthClientRegistrationError as exc:
        return client, [], _redirect_with(
            redirect_uri, {"error": "invalid_scope", "error_description": str(exc)}
        )
    if not scopes:
        return client, [], _redirect_with(
            redirect_uri, {"error": "invalid_scope", "error_description": "At least one scope is required"}
        )
    return client, scopes, None


def _resolved_resource(
    request: Request, raw: str | None, *, redirect_uri: str, state: str
) -> tuple[str | None, RedirectResponse | None]:
    """RFC 8707: only known resource indicators; the raw value is never echoed.

    Called only after client_id and redirect_uri were validated, so a refusal
    redirects ``error=invalid_target`` to the registered redirect_uri.
    """
    try:
        return resolve_resource_indicator(raw, issuer=str(request.base_url)), None
    except OAuthFlowError as exc:
        params = {"error": exc.error, "error_description": exc.description}
        if state:
            params["state"] = state
        return None, _redirect_with(redirect_uri, params)


def _code_redirect(redirect_uri: str, *, code: str, state: str) -> RedirectResponse:
    response_params = {"code": code}
    if state:
        response_params["state"] = state
    return _redirect_with(redirect_uri, response_params)


def _login_redirect(request: Request) -> RedirectResponse:
    # The login accepts only a same-site relative path as ``next``; an absolute URL is dropped there and the user
    # lands in /chat instead of back on this consent (live: native Codex MCP OAuth never completed).
    next_url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(url=f"/chat/login?{urlencode({'next': next_url})}", status_code=302)


@router.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    params = request.query_params
    client, scopes, error = await _validated_request(
        request,
        db,
        client_id=params.get("client_id"),
        redirect_uri=params.get("redirect_uri"),
        response_type=params.get("response_type"),
        scope=params.get("scope"),
        code_challenge=params.get("code_challenge"),
        code_challenge_method=params.get("code_challenge_method"),
    )
    if error is not None:
        return error
    redirect_uri = str(params.get("redirect_uri"))
    state = params.get("state") or ""
    resource, error = _resolved_resource(request, params.get("resource"), redirect_uri=redirect_uri, state=state)
    if error is not None:
        return error

    user_id = _get_user_from_cookie(request)
    if not user_id:
        return _login_redirect(request)

    grant = await find_reusable_grant(db, user_id=user_id, client_id=client.client_id, scopes=scopes)
    if grant is not None:
        code = await issue_authorization_code(
            db,
            grant=grant,
            client_id=client.client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            code_challenge=str(params.get("code_challenge")),
            code_challenge_method="S256",
            resource=resource,
        )
        return _code_redirect(redirect_uri, code=code, state=state)

    return templates.TemplateResponse(
        request,
        "oauth_consent.html",
        {
            "error_message": None,
            "client_name": client.client_name,
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "scopes": scopes,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": params.get("code_challenge"),
            "resource": resource or "",
        },
    )


@router.post("/oauth/authorize/decision")
async def oauth_authorize_decision(
    request: Request,
    decision: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form(...),
    state: str = Form(default=""),
    code_challenge: str = Form(...),
    resource: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    validate_browser_origin_headers(request, require_headers=True)
    client, scopes, error = await _validated_request(
        request,
        db,
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type="code",
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    if error is not None:
        return error
    audience, error = _resolved_resource(request, resource, redirect_uri=redirect_uri, state=state)
    if error is not None:
        return error

    user_id = _get_user_from_cookie(request)
    if not user_id:
        return _login_redirect(request)

    if decision != "approve":
        params = {"error": "access_denied"}
        if state:
            params["state"] = state
        return _redirect_with(redirect_uri, params)

    login_session_id = await _newest_login_session_id(db, user_id)
    grant = await create_grant(
        db,
        user_id=user_id,
        client_id=client.client_id,
        scopes=scopes,
        project_ids=None,
        platform_refresh_token_id=login_session_id,
    )
    code = await issue_authorization_code(
        db,
        grant=grant,
        client_id=client.client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        code_challenge=code_challenge,
        code_challenge_method="S256",
        resource=audience,
    )
    return _code_redirect(redirect_uri, code=code, state=state)
