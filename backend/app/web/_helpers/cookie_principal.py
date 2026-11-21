"""Authoritative cookie/bearer principal for the web surface.

Every route under ``/chat`` and ``/admin`` authenticates from the same auth
cookie (or, for non-browser callers, the same bearer token). Until the rule
"the account must still be active" lived only in the authenticated API's
:func:`app.services.auth.get_current_user`: the web helper resolved a ``User``
row and stopped there, so a deactivated account kept authenticating on the panel
surface until its cookie expired. ``_require_admin_api`` then asked only for the
global-admin *role*, which a deactivated admin still holds, and
``require_permission`` answered 403 — after the principal had already been
resolved and attributed.

This module is the single owner of that decision for the web surface:

- :func:`principal_id_from_request` is the only place a token is taken from the
  request (cookie first, bearer second) and decoded.
- :func:`load_active_principal` returns a ``User`` only when the row exists *and*
  ``is_active`` is true. It reads; it never writes.
- The two ``require_*`` wrappers differ only in how they refuse: the API surface
  answers 401 with the same detail ``/api/v1`` uses, the page surface keeps its
  307 redirect to the login page.

The refusal happens before the caller runs any authorization check, service
call, audit attribution or persistence, because the guard *is* the caller's
first statement (proved per served route by
``tests/test_panel_mutation_inventory_gate.py``). Neither refusal names a
resource, so it cannot be used to probe what exists behind the boundary.

Why nothing is persisted on the refusal path — and how the event stays visible:

The 401 must precede *any* audit attribution or persistence, so this
module deliberately does **not** write the ``auth.access.denied`` row that
:func:`app.services.auth.get_current_user` writes on ``/api/v1``. Writing one
here would mean a denied, unauthenticated caller could make the request commit a
row — a row attributed to the account whose credential it presented — which is
exactly the ordering this rule prevents, and on the panel surface it would also be
a cheap unauthenticated write amplifier.

The visibility tradeoff is paid two ways instead, neither of which persists
anything before the denial:

1. A refusal is logged here, at ``WARNING``, with an enum-like reason and
   nothing else: no user id, no token, no path, no address, no header value.
   Volume in the log is the aggregate signal that a revoked credential is still
   being used.
2. The generic request audit (:mod:`app.middleware.audit.request_audit`) still
   records the attempt, because it runs *around* the route and writes only
   *after* the response is produced. Its row carries the refused status code, so
   it records a denied attempt and never a mutation. It attributes a
   cookie-only caller to the anonymous audit principal, so the denial does not
   put the deactivated account's id on a row that looks like work it did.
"""

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


def _log_refusal(reason: str) -> None:
    """Record one refusal without persisting or identifying anything.

    Only the fixed reason is logged — no user id, token, path, address or header
    value — so the line is safe wherever logs are shipped. The durable record of
    the attempt is the generic request audit, which writes after the response.
    """
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
    """Subject of the auth cookie, or of a bearer token when no cookie is sent.

    Returns ``None`` for an absent or undecodable token. The token value itself
    never leaves this function.
    """
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
    """Resolve the active principal for *request*.

    Returns ``(user, "")`` when the principal is active, and ``(None, detail)``
    otherwise. The detail distinguishes "no credential" from "unknown or
    deactivated" exactly as the authenticated API does; both are refusals of the
    same class and neither reveals anything beyond the caller's own identity.

    Read-only on every path, including the refusal paths: no row is added,
    changed or committed before the caller raises. See the module docstring for
    why, and for where the refusal stays visible.
    """
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
    """Active principal for a JSON surface, or 401 before anything else runs."""
    user, detail = await load_active_principal(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    return user


async def require_active_page_principal(request: Request, db: AsyncSession) -> User:
    """Active principal for an HTML surface, or a redirect to the login page.

    The page contract is unchanged: an unusable principal — missing, unknown or
    deactivated — is sent to the login page rather than shown an error, and the
    three cases are not distinguishable from the response.
    """
    user, _ = await load_active_principal(request, db)
    if user is None:
        raise HTTPException(status_code=307, headers={"Location": LOGIN_REDIRECT_PATH})
    return user
