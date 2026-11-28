"""The authoritative cookie or bearer principal of the web surface: an active account, or a refusal."""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User

logger = logging.getLogger(__name__)
root_logger = logging.getLogger()

LOGIN_REDIRECT_PATH = "/chat/login"

#: Detail for a caller that presented no usable credential at all.
UNAUTHENTICATED_DETAIL = "Authentication required"
#: Detail for a decoded principal that is unknown or deactivated. Byte-identical
#: to ``app.services.auth.get_current_user`` so a principal denied on ``/api/v1``
#: is denied identically here, and so the two cases stay indistinguishable.
INACTIVE_PRINCIPAL_DETAIL = "User not found or inactive"

__all__ = [
    "INACTIVE_PRINCIPAL_DETAIL",
    "LOGIN_REDIRECT_PATH",
    "REFUSAL_INACTIVE_PRINCIPAL",
    "REFUSAL_UNKNOWN_PRINCIPAL",
    "UNAUTHENTICATED_DETAIL",
    "load_active_principal",
    "principal_id_from_request",
    "require_active_api_principal",
    "require_active_page_principal",
]


def _log_warning(message: str, *args: object) -> None:
    logger.warning(message, *args, exc_info=True)
    if logger.disabled or not logger.propagate:
        root_logger.warning(message, *args, exc_info=True)


#: Enum-like refusal reasons. Safe to log: each is a fixed constant, never a
#: value taken from the request.
REFUSAL_UNKNOWN_PRINCIPAL = "unknown_principal"
REFUSAL_INACTIVE_PRINCIPAL = "inactive_principal"

_REFUSAL_LOG_MESSAGE = "Web surface refused a principal before authorization (reason=%s)"


# Nothing is persisted before a refusal; the request audit records the attempt after the response.
def _log_refusal(reason: str) -> None:
    logger.warning(_REFUSAL_LOG_MESSAGE, reason)
    if logger.disabled or not logger.propagate:
        root_logger.warning(_REFUSAL_LOG_MESSAGE, reason)


def _request_token(request: Request) -> str:
    from ...services.auth.service import cookie_access_token  # web login first, then the phone's own cookie

    token = cookie_access_token(request)
    if not token:
        authorization = str(request.headers.get("authorization") or "").strip()
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            token = value.strip()
    return str(token or "")


def principal_id_from_request(request: Request, *, allow_phone: bool = False) -> str | None:
    token = _request_token(request)
    if not token:
        return None
    from ...services.auth import decode_token

    try:
        return decode_token(token, allow_phone=allow_phone)
    except Exception:
        _log_warning("Failed to decode auth token from cookie or bearer header")
        return None


async def load_active_principal(request: Request, db: AsyncSession) -> tuple[User | None, str]:
    resolved = getattr(request.state, "active_principal", None)
    if resolved is not None and resolved[0] is db:
        return resolved[1]
    principal = await _resolve_active_principal(request, db)
    request.state.active_principal = (db, principal)
    return principal


async def _resolve_active_principal(request: Request, db: AsyncSession) -> tuple[User | None, str]:
    user_id = principal_id_from_request(request, allow_phone=True)
    if not user_id:
        return None, UNAUTHENTICATED_DETAIL

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        _log_refusal(REFUSAL_UNKNOWN_PRINCIPAL)
        return None, INACTIVE_PRINCIPAL_DETAIL
    if not user.is_active:
        _log_refusal(REFUSAL_INACTIVE_PRINCIPAL)
        return None, INACTIVE_PRINCIPAL_DETAIL
    # A paired phone's token (Octryx Mobile): a revoked or expired phone is refused on its next request.
    from ...services.mobile.session import mobile_access_refusal

    if await mobile_access_refusal(db, _request_token(request), user_id=user.id, method=request.method,
                                   path=request.url.path):
        _log_refusal(REFUSAL_INACTIVE_PRINCIPAL)
        return None, INACTIVE_PRINCIPAL_DETAIL
    return user, ""


async def require_active_api_principal(request: Request, db: AsyncSession) -> User:
    user, detail = await load_active_principal(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    return user


async def require_active_page_principal(request: Request, db: AsyncSession) -> User:
    user, _ = await load_active_principal(request, db)
    if user is None:
        raise HTTPException(status_code=307, headers={"Location": LOGIN_REDIRECT_PATH})
    return user
