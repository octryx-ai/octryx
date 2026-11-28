"""Platform feature switch for custom branding. Off by default (``BRANDING_ENABLED``): reads return the defaults and
writes refuse with ``branding_disabled``."""

from __future__ import annotations

from fastapi import HTTPException

from app.config import get_settings

BRANDING_DISABLED_CODE = "branding_disabled"
BRANDING_DISABLED_MESSAGE = "Branding is disabled on this platform."


def branding_enabled() -> bool:
    return bool(get_settings().branding_enabled)


def require_branding_enabled() -> None:
    if not branding_enabled():
        raise HTTPException(
            status_code=409,
            detail={"code": BRANDING_DISABLED_CODE, "message": BRANDING_DISABLED_MESSAGE},
        )
