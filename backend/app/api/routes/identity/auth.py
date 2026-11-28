from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import get_settings
from ....db import get_db
from ....http_multipart_route import SelfAuthenticatedFormRoute
from ....http_security import clear_auth_cookies, set_auth_cookies
from ....models import User
from ....schemas.core.auth import LoginResponse, RefreshTokenRequest, UserResponse
from ....services.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    revoke_refresh_token,
    user_has_permission,
    verify_password,
)
from ....services.auth.audit import record_auth_audit_event
from ....services.auth.login_mode import (
    PASSWORD_LOGIN_DISABLED_DETAIL,
    password_login_disabled,
    record_password_login_refused,
)
from ....services.auth_rate_limit import (
    AUTH_REFRESH_SCOPE,
    clear_auth_failures,
    get_auth_rate_limit_state,
    register_auth_failure,
)
from ....services.auth_rate_limit import login as login_limit  # per address and per username
from ....services.oidc import (
    build_oidc_authorization_redirect,
    complete_oidc_callback,
    list_public_oidc_providers,
    refresh_access_token,
)
from ....web._helpers.api_guards import _enforce_same_origin_for_cookie_auth
from .auth_users import role_names, user_response

router = APIRouter(prefix="/api/v1/auth", tags=["auth"], route_class=SelfAuthenticatedFormRoute)


def _require_same_origin_refresh_cookie(request: Request) -> None:
    _enforce_same_origin_for_cookie_auth(request, cookie_names=("refresh_token",))


async def _refuse_login(
    db: AsyncSession, request: Request, *, user_id: str | None, action: str, reason: str, username: str
) -> None:
    # Committed before the refusal is raised, so the audit row survives it.
    record_auth_audit_event(
        db,
        user_id=user_id,
        action=action,
        details={"reason": reason, "username": username},
        request=request,
    )
    await db.commit()


async def _checked_login_user(db: AsyncSession, request: Request, form_data: OAuth2PasswordRequestForm) -> User:
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        login_limit.register_failure(request, form_data.username)
        await _refuse_login(db, request, user_id=user.id if user else None, action="auth.login.failed",
                            reason="invalid_credentials", username=form_data.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        await _refuse_login(db, request, user_id=user.id, action="auth.login.blocked", reason="inactive_user",
                            username=form_data.username)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    if not await user_has_permission(db, user.id, resource="auth", action="login"):
        await _refuse_login(db, request, user_id=user.id, action="auth.login.blocked",
                            reason="missing_auth_login_permission", username=form_data.username)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login is not permitted for this user")
    return user


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    if await password_login_disabled(db):
        # SSO-only: refused before the credentials are checked, so the answer is no password oracle.
        await record_password_login_refused(db, username=form_data.username, method="password", request=request)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PASSWORD_LOGIN_DISABLED_DETAIL)

    rate_limit_state = login_limit.state(request, form_data.username)
    if rate_limit_state.limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Try again in {rate_limit_state.retry_after_seconds} seconds.",
            headers={"Retry-After": str(rate_limit_state.retry_after_seconds)},
        )

    user = await _checked_login_user(db, request, form_data)

    login_limit.clear(request, form_data.username)
    token = create_access_token(user.id)
    refresh_token = await create_refresh_token(db, user_id=user.id)
    record_auth_audit_event(
        db,
        user_id=user.id,
        action="auth.login.succeeded",
        details={"method": "password", "username": form_data.username},
        request=request,
    )
    await db.commit()
    return LoginResponse(access_token=token, token_type="bearer", refresh_token=refresh_token)


def _oidc_redirect_uri(request: Request) -> str:
    # The provider needs the public callback URL, which can differ from the URL this app sees behind a proxy.
    origin = str(get_settings().platform_public_origin or "").strip().rstrip("/")
    if origin:
        return f"{origin}{request.app.url_path_for('oidc_callback')}"
    return str(request.url_for("oidc_callback"))


@router.get("/oidc/providers")
async def list_oidc_providers(db: AsyncSession = Depends(get_db)):
    return await list_public_oidc_providers(db)


@router.get("/oidc/start/{provider_id}")
async def start_oidc_login(
    provider_id: str,
    request: Request,
    target: str = "/chat",
    db: AsyncSession = Depends(get_db),
):
    redirect_uri = _oidc_redirect_uri(request)
    authorization_url = await build_oidc_authorization_redirect(
        db,
        provider_id=provider_id,
        redirect_uri=redirect_uri,
        target_path=target,
    )
    return RedirectResponse(url=authorization_url, status_code=307)


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(
    request: Request,
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if error:
        raise HTTPException(status_code=400, detail=f"OIDC login failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="OIDC callback missing authorization code")
    result = await complete_oidc_callback(
        db,
        state=state,
        code=code,
        redirect_uri=_oidc_redirect_uri(request),
    )
    response = RedirectResponse(url=result["redirect_path"], status_code=303)
    set_auth_cookies(
        response,
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        request=request,
    )
    return response


@router.post("/refresh", response_model=LoginResponse)
async def refresh_login(
    request: Request,
    body: RefreshTokenRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Rate-limit token refresh attempts so a stolen or guessed refresh token cannot be hammered.
    rate_limit_state = get_auth_rate_limit_state(AUTH_REFRESH_SCOPE, request)
    if rate_limit_state.limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many refresh attempts. Try again in {rate_limit_state.retry_after_seconds} seconds.",
            headers={"Retry-After": str(rate_limit_state.retry_after_seconds)},
        )

    body_token = body.refresh_token if body else None
    cookie_token = request.cookies.get("refresh_token")
    if cookie_token and not body_token:
        _require_same_origin_refresh_cookie(request)
    token = body_token or cookie_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required")
    try:
        refreshed = await refresh_access_token(db, refresh_token=token)
    except Exception:
        register_auth_failure(AUTH_REFRESH_SCOPE, request)
        raise
    clear_auth_failures(AUTH_REFRESH_SCOPE, request)
    record_auth_audit_event(
        db,
        user_id=refreshed["user"].id,
        action="auth.refresh.succeeded",
        details={"method": "refresh_token"},
        request=request,
    )
    await db.commit()
    return LoginResponse(
        access_token=refreshed["access_token"],
        token_type="bearer",
        refresh_token=refreshed["refresh_token"],
    )


@router.post("/logout", response_model=dict)
async def logout(
    request: Request,
    body: RefreshTokenRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    body_token = body.refresh_token if body else None
    cookie_token = request.cookies.get("refresh_token")
    if cookie_token and not body_token:
        _require_same_origin_refresh_cookie(request)
    token = body_token or cookie_token
    revoked = await revoke_refresh_token(db, token) if token else None
    if revoked is not None:
        record_auth_audit_event(
            db,
            user_id=revoked.user_id,
            action="auth.refresh_token.revoked",
            resource_type="refresh_token",
            resource_id=revoked.id,
            details={"reason": "logout"},
            request=request,
        )
        record_auth_audit_event(
            db,
            user_id=revoked.user_id,
            action="auth.logout.succeeded",
            details={"refresh_token_revoked": True},
            request=request,
        )
        await db.commit()

    response = JSONResponse({"ok": True, "refresh_token_revoked": revoked is not None})
    clear_auth_cookies(response, request=request)
    return response


@router.get("/whoami", response_model=UserResponse)
async def whoami(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    roles = await role_names(db, current_user.id)

    return user_response(current_user, roles)
