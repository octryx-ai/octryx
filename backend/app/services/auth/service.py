"""Authentication helpers used by API and web route dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.api import AuthenticationError, AuthorizationError

from ...db import get_db
from ...http_security import API_KEY_HEADER
from ...models import Role, User, UserRole
from ..api_key import authenticate_api_key
from .audit import record_auth_audit_event
from .tokens import cookie_access_token, decode_token

security = HTTPBearer(auto_error=False)


def _check_api_key_scope(api_key_scopes: list[str] | None, required_scope: str) -> bool:
    if not api_key_scopes:
        return False
    return required_scope in {str(s).strip().lower() for s in api_key_scopes}


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    raw_api_key = str(request.headers.get(API_KEY_HEADER) or "").strip()
    if raw_api_key:
        user, api_key = await authenticate_api_key(db, raw_api_key)
        request.state.api_key_id = api_key.id
        request.state.api_key_project_id = api_key.project_id
        request.state.api_key_scopes = list(api_key.scopes or [])  # the key's scopes bound the request
        return user
    bearer_token = str(credentials.credentials or "").strip() if credentials else ""
    token = bearer_token or cookie_access_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        user_id = decode_token(token, allow_phone=True)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc.detail or "Invalid token"),
        ) from exc
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        if user is not None:
            record_auth_audit_event(
                db,
                user_id=user.id,
                action="auth.access.denied",
                details={"reason": "inactive_user", "auth_method": "bearer_or_cookie"},
                request=request,
            )
            await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    # A paired phone's token (Octryx Mobile): the phone itself must still be valid (revoking acts now) and it only
    # reaches the surfaces the phone app uses.
    from ..mobile.session import mobile_access_refusal  # noqa: PLC0415 - mobile builds on this module

    if await mobile_access_refusal(db, token, user_id=user.id, method=request.method, path=request.url.path):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phone not paired")
    return user


async def require_role(*role_names: str):
    """Dependency factory: require specific roles."""

    async def role_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        result = await db.execute(
            select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == current_user.id)
        )
        user_roles = {row[0] for row in result.all()}
        if not user_roles.intersection(set(role_names)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(
                    AuthorizationError(
                        f"Requires one of roles: {', '.join(role_names)}",
                        required_roles=list(role_names),
                    )
                ),
            )
        return current_user

    return role_checker


def require_api_key_scope(*required_scopes: str):
    """Dependency factory: require API key to have one of the given scopes."""

    async def scope_checker(request: Request) -> None:
        if not hasattr(request.state, "api_key_id"):
            return  # bearer token auth — skip scope check
        api_key_scopes = list(getattr(request.state, "api_key_scopes", []) or [])
        if not any(_check_api_key_scope(api_key_scopes, s) for s in required_scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key lacks required scope. Required: {', '.join(required_scopes)}",
            )

    return scope_checker
