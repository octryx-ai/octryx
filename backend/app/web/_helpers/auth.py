"""Auth and provider config helpers."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...http_security import current_request_origin
from ...models import User
from .cookie_principal import principal_id_from_request, require_active_page_principal

__all__ = [
    "COPILOT_DEVICE_FLOW_STATE",
    "THINKING_LEVELS",
    "_get_user_from_cookie",
    "_require_user",
    "validate_browser_origin_headers",
]

COPILOT_DEVICE_FLOW_STATE: dict[str, dict] = {}
THINKING_LEVELS = ["off", "light", "deep"]


def _normalize_browser_header_origin(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def validate_browser_origin_headers(request: Request, *, require_headers: bool = False) -> None:
    expected_origin = current_request_origin(request)
    origin = _normalize_browser_header_origin(request.headers.get("origin"))
    if origin:
        if origin != expected_origin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site request blocked")
        return

    referer_origin = _normalize_browser_header_origin(request.headers.get("referer"))
    if referer_origin:
        if referer_origin != expected_origin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site request blocked")
        return

    if require_headers:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing same-origin browser headers")


def _get_user_from_cookie(request: Request) -> str | None:
    """Extract user_id from JWT cookie or bearer token or return None.

    The decision itself belongs to :mod:`app.web._helpers.cookie_principal`.
    """
    return principal_id_from_request(request)


async def _require_user(request: Request, db: AsyncSession) -> User:
    """Active current user from the cookie, or a redirect to the login page.

    Thin alias for the authoritative page guard: a deactivated account is
    not resolved here, so no page route can attribute work to one.
    """
    return await require_active_page_principal(request, db)
