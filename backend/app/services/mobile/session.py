"""The phone's web session: short access tokens that name the phone, checked on every request."""

from __future__ import annotations

import re

import jwt
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth.tokens import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER

from ...auth_cookie_policy import PHONE_ACCESS_COOKIE
from ...config import get_settings
from ...models import MobileDevice
from ...time_utils import utc_now_aware
from ..auth.service import decode_token
from .contract import ACCESS_CLAIM, ACCESS_TOKEN_TTL, REASON_SURFACE
from .devices import phone_refusal

# (method or "*", path pattern): what the Home Screen app calls. Everything else refuses a phone's token.
PHONE_SURFACES: tuple[tuple[str, re.Pattern[str]], ...] = tuple((method, re.compile(pattern)) for method, pattern in (
    ("POST", r"^/api/v1/mobile/(session|logout)$"),
    ("GET", r"^/api/v1/mobile/(devices|usage|sessions|push|local-sessions)$"),
    ("POST", r"^/api/v1/mobile/local-sessions/[^/]+/messages$"),
    ("*", r"^/api/v1/mobile/push$"),
    ("POST", r"^/api/v1/mobile/devices/[^/]+/revoke$"),
    ("GET", r"^/api/v1/mobile/live$"),
    ("POST", r"^/api/v1/mobile/live/fork$"),
    ("GET", r"^/api/v1/mobile/live/progress$"),
    # Work items: read them and steer existing runs; limits, new-session route, events and bindings stay off the phone.
    ("GET", r"^/api/v1/secure-work/work-items$"),
    # Each checks the item's Workspace scope; the other per-item routes stay off the phone.
    ("GET", r"^/api/v1/secure-work/work-items/[^/]+(/change-plans|/progress)?$"),
    ("GET", r"^/api/v1/workflow-runs$"),
    # Starting a run: the person's own devices only (a foreign device is refused); scope is checked first.
    ("GET", r"^/api/v1/workflow-runs/(startable|runtime-targets)$"),
    ("POST", r"^/api/v1/workflow-runs$"),
    ("GET", r"^/api/v1/workflow-runs/(?!limits$|startable$|runtime-targets$|by-session$|work-items$)[^/]+$"),
    ("POST", r"^/api/v1/workflow-runs/(?!limits$|startable$|runtime-targets$|by-session$|work-items$)[^/]+/actions$"),
    # Artifacts of a Server chat: read-only previews; the routes keep their own owner checks.
    ("GET", r"^/chat/api/artifact-preview$"),
    ("GET", r"^/chat/api/artifact-image$"),
    ("*", r"^/api/v1/mobile/live/messages$"),
    ("GET", r"^/api/v1/devices$"),
    ("*", r"^/api/v1/device-jobs(/.*)?$"),
    ("GET", r"^/api/v1/attention$"),
    ("POST", r"^/api/v1/attention/dismiss$"),
    ("GET", r"^/api/v1/workspaces/[^/]+/agent-gateway/device-runs(/models)?$"),
    # Seat switches, read-only: the route checks membership; changing a switch stays in the web.
    ("GET", r"^/api/v1/workspaces/[^/]+/agent-gateway/seat-mode$"),
    ("GET", r"^/chat/api/bootstrap$"),
    ("GET", r"^/chat/api/thread-groups$"),
    ("POST", r"^/chat/api/send$"),
    # Approve or reject one connector write: the route checks who may decide; "Always" stays in the web.
    ("POST", r"^/chat/api/approvals/[^/]+/(approve|reject)$"),
    ("GET", r"^/chat/api/sessions/[^/]+/(messages|view)$"),
    # A held workflow proposal: the route checks the session's owner and the catalog itself.
    ("POST", r"^/chat/api/sessions/[^/]+/workflow-proposal$"),
    ("GET", r"^/chat/api/workflows$"),
    # Roles, read-only: the routes check membership and admin rights; every write stays in the web.
    ("GET", r"^/api/v1/work-roles/workspaces/[^/]+(/me)?$"),
    # Plugin pages: the bridge runs every call as the viewer; installing, disabling and settings stay in the web.
    ("GET", r"^/api/v1/plugins$"),
    ("GET", r"^/api/v1/plugins/[^/]+/ui$"),
    ("POST", r"^/api/v1/plugins/[^/]+/bridge$"),
    ("GET", r"^/api/v1/approvals/[^/]+$"),
    # Approvals this person may decide: the same decision checks as the web; "Always" stays in the web.
    ("POST", r"^/api/v1/approvals/[^/]+/(approve|reject)$"),
))


def phone_may_use(method: str, path: str) -> bool:
    verb = method.upper()
    return any((allowed in ("*", verb)) and pattern.match(path) for allowed, pattern in PHONE_SURFACES)


def mint_mobile_access_token(*, user_id: str, device_id: str) -> str:
    settings = get_settings()
    payload = {"sub": user_id, "exp": utc_now_aware() + ACCESS_TOKEN_TTL, "aud": JWT_AUDIENCE, "iss": JWT_ISSUER,
               ACCESS_CLAIM: device_id}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def mobile_session_id(token: str) -> str:
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return ""
    value = claims.get(ACCESS_CLAIM) if isinstance(claims, dict) else None
    return value if isinstance(value, str) else ""


def verified_phone_id(token: str, *, user_id: str) -> str:
    try:
        if decode_token(token, allow_phone=True) != user_id:
            return ""
    except HTTPException:  # any invalid token is no phone
        return ""
    return mobile_session_id(token)


def request_phone_id(request: Request, *, user_id: str) -> str:
    return verified_phone_id(str(request.cookies.get(PHONE_ACCESS_COOKIE) or ""), user_id=user_id)


async def mobile_access_refusal(db: AsyncSession, token: str, *, user_id: str, method: str, path: str) -> str:
    device_id = mobile_session_id(token)
    if not device_id:
        return ""
    if not phone_may_use(method, path):
        return REASON_SURFACE
    device = await db.get(MobileDevice, device_id)
    if device is not None and device.owner_user_id != user_id:
        device = None
    return await phone_refusal(db, device)


__all__ = ["PHONE_SURFACES", "mint_mobile_access_token", "mobile_access_refusal", "mobile_session_id", "phone_may_use",
           "request_phone_id", "verified_phone_id"]
