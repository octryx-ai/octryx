"""Auto-extracted router module: auth."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...http_multipart_route import SelfAuthenticatedFormRoute
from ...http_security import clear_auth_cookies, set_auth_cookies
from ...services.auth import first_admin
from ...services.auth.login_mode import (
    PASSWORD_LOGIN_DISABLED_DETAIL,
    password_login_disabled,
    record_password_login_refused,
)
from ...services.auth_rate_limit import login as login_limit  # per address and per username
from ...services.oidc import (
    list_identity_providers as admin_list_identity_providers,
)
from ...services.oidc import (
    serialize_identity_provider,
)
from .._context import templates
from .._helpers.auth import validate_browser_origin_headers

router = APIRouter(route_class=SelfAuthenticatedFormRoute)



def _safe_next_path(raw: str | None) -> str | None:
    # Only same-origin relative paths are honored as post-login targets.
    value = str(raw or "").strip()
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if await first_admin.pending_admin(db) is not None:
        return RedirectResponse(url=first_admin.SETUP_PATH, status_code=303)
    auth_oidc_only = await password_login_disabled(db)
    providers = [
        provider
        for provider in await admin_list_identity_providers(db, active_only=True)
        if (provider.provider_type or "").lower() == "oidc"
    ]
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "auth_oidc_only": auth_oidc_only,
            "oidc_providers": [serialize_identity_provider(provider) for provider in providers],
            "next": _safe_next_path(request.query_params.get("next")) or "",
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    from ...services.auth import authenticate_user, create_access_token, create_refresh_token
    from ...services.auth.audit import record_auth_audit_event

    validate_browser_origin_headers(request)
    if await password_login_disabled(db):
        await record_password_login_refused(db, username=username, method="password_web", request=request)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": PASSWORD_LOGIN_DISABLED_DETAIL, "auth_oidc_only": True},
            status_code=403,
        )
    rate_limit_state = login_limit.state(request, username)
    if rate_limit_state.limited:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": f"Too many login attempts. Try again in {rate_limit_state.retry_after_seconds} seconds."},
            status_code=429,
            headers={"Retry-After": str(rate_limit_state.retry_after_seconds)},
        )

    user = await authenticate_user(db, username, password)
    if not user:
        login_limit.register_failure(request, username)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid credentials"},
            status_code=401,
        )

    login_limit.clear(request, username)
    token = create_access_token(user.id)
    refresh_token = await create_refresh_token(db, user_id=user.id)
    record_auth_audit_event(
        db,
        user_id=user.id,
        action="auth.login.succeeded",
        details={"method": "password_web", "username": username},
        request=request,
    )
    await db.commit()
    response = RedirectResponse(url=_safe_next_path(next) or "/chat", status_code=303)
    set_auth_cookies(response, access_token=token, refresh_token=refresh_token, request=request)
    return response


@router.get("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    from ...services.auth import revoke_refresh_token
    from ...services.auth.audit import record_auth_audit_event

    validate_browser_origin_headers(request)
    refresh_token = str(request.cookies.get("refresh_token") or "").strip()
    revoked = None
    if refresh_token:
        revoked = await revoke_refresh_token(db, refresh_token)
    if revoked is not None:
        record_auth_audit_event(
            db,
            user_id=revoked.user_id,
            action="auth.refresh_token.revoked",
            resource_type="refresh_token",
            resource_id=revoked.id,
            details={"reason": "web_logout"},
            request=request,
        )
        record_auth_audit_event(
            db,
            user_id=revoked.user_id,
            action="auth.logout.succeeded",
            details={"refresh_token_revoked": True, "method": "web"},
            request=request,
        )
        await db.commit()
    response = RedirectResponse(url="/chat/login", status_code=303)
    clear_auth_cookies(response, request=request)
    return response


_SETUP_RATE_LIMIT_KEY = "first-admin-setup"


def _setup_page(request: Request, *, status_code: int = 200, **context):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"setup": True, "min_password_chars": first_admin.MIN_PASSWORD_CHARS, **context},
        status_code=status_code,
    )


@router.get("/setup", response_class=HTMLResponse)
async def first_admin_setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    """First start only: the form that creates the administrator (services/auth/first_admin.py)."""
    if await first_admin.pending_admin(db) is None:
        return RedirectResponse(url="/chat/login", status_code=303)
    return _setup_page(request)


@router.post("/setup")
async def first_admin_setup_submit(
    request: Request,
    code: str = Form(...),
    display_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from ...services.auth import create_access_token, create_refresh_token
    from ...services.auth.audit import record_auth_audit_event

    validate_browser_origin_headers(request)
    rate_limit_state = login_limit.state(request, _SETUP_RATE_LIMIT_KEY)
    if rate_limit_state.limited:
        return _setup_page(
            request,
            status_code=429,
            error=f"Too many attempts. Try again in {rate_limit_state.retry_after_seconds} seconds.",
        )
    try:
        user = await first_admin.complete_first_admin(
            db, code=code, display_name=display_name, email=email, password=password
        )
    except first_admin.FirstAdminSetupClosedError:
        return templates.TemplateResponse(
            request, "login.html", {"error": "The administrator is already set up. Sign in instead."}, status_code=409
        )
    except first_admin.FirstAdminSetupRejectedError as exc:
        login_limit.register_failure(request, _SETUP_RATE_LIMIT_KEY)
        return _setup_page(request, status_code=400, error=str(exc), display_name=display_name, email=email)

    login_limit.clear(request, _SETUP_RATE_LIMIT_KEY)
    record_auth_audit_event(
        db, user_id=user.id, action="auth.first_admin.created", details={"method": "setup_code"}, request=request
    )
    token = create_access_token(user.id)
    refresh_token = await create_refresh_token(db, user_id=user.id)
    await db.commit()
    # Straight into the Setup guide: it shows what the fresh installation still needs.
    response = RedirectResponse(url="/chat?area=help&tab=setup", status_code=303)
    set_auth_cookies(response, access_token=token, refresh_token=refresh_token, request=request)
    return response
