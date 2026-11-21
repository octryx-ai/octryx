"""The phone's web session: short access tokens that name the phone, checked on every request.

The Home Screen app holds its own credential (the httpOnly ``octryx_mobile`` cookie, sent only to
``/api/v1/mobile``). With it, ``POST /api/v1/mobile/session`` issues an ordinary platform access token that lives
five minutes and carries the phone's id (``msid``), set as the phone's own ``octryx_phone_access`` cookie (path ``/``),
never as the web login's ``access_token``: a browser used for the web app and ``/m`` keeps both logins, and signing
out on the phone leaves the web login alone. ``services.auth.service.cookie_access_token`` takes a
valid web token from ``access_token`` first and otherwise only a phone token from ``octryx_phone_access``. So the phone
uses the same APIs as the web app, and:

- ``get_current_user`` and the chat API's principal check call :func:`mobile_access_refusal` for such a token: a
  revoked or expired phone (or one whose originating octryx-claude login was revoked) is refused on its next
  request, and the token reaches only the surfaces the phone app uses (:data:`PHONE_SURFACES`): no admin, no
  credentials (API keys, OAuth consent, passwords), no WebSocket (``decode_token`` refuses a phone's token unless
  the caller checks the phone).
"""

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
    ("POST", r"^/api/v1/mobile/live/fork$"),  # continue a copy of an idle listed session
    ("GET", r"^/api/v1/mobile/live/progress$"),  # what a listed session is doing
    # Cases: read the Work items and their runs, steer an existing run. The limits, the
    # run's new-session route, its events and bindings stay off the phone.
    ("GET", r"^/api/v1/secure-work/work-items$"),
    # A task's detail and its change plans: both check the item's Workspace scope. The other
    # per-item routes (pull requests, CI, coding, transitions, close) stay off the phone.
    ("GET", r"^/api/v1/secure-work/work-items/[^/]+(/change-plans)?$"),
    ("GET", r"^/api/v1/workflow-runs$"),
    # Starting a run for a task: the workflows a run can start,
    # where it may run (the person's own devices only; a foreign device is refused by the platform), and the start
    # itself (scope checked first, as in the web).
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
    # More › Seat: the Workspace's two seat switches, read-only. The route checks membership itself;
    # changing a switch (PUT) stays in the web.
    ("GET", r"^/api/v1/workspaces/[^/]+/agent-gateway/seat-mode$"),
    ("GET", r"^/chat/api/bootstrap$"),
    ("GET", r"^/chat/api/thread-groups$"),
    ("POST", r"^/chat/api/send$"),
    # A Server chat's connector write waits for the person: approve or reject that one call from the phone
    #The route checks who may decide; "Always for this Workspace" stays in the web.
    ("POST", r"^/chat/api/approvals/[^/]+/(approve|reject)$"),
    ("GET", r"^/chat/api/sessions/[^/]+/(messages|view)$"),
    # A chat's held workflow proposal on the phone (chat parity): answer it (start, don't
    # start, allow, deny, another workflow from the catalog) and read that catalog. The route checks the session's
    # owner and the catalog itself; the run locations are listed above (runtime-targets).
    ("POST", r"^/chat/api/sessions/[^/]+/workflow-proposal$"),
    ("GET", r"^/chat/api/workflows$"),
    # Roles, read-only: "My role" for every member and the Workspace's assignments for its admins. The
    # routes check membership and admin rights themselves; every write (assignments, the switch) stays in the web.
    ("GET", r"^/api/v1/work-roles/workspaces/[^/]+(/me)?$"),
    # Plugin pages on the phone: the list, a page's frame and its bridge
    # (which runs every call as the viewer), and an approval's bounded metadata for the confirm dialog. Installing,
    # disabling and settings stay in the web.
    ("GET", r"^/api/v1/plugins$"),
    ("GET", r"^/api/v1/plugins/[^/]+/ui$"),
    ("POST", r"^/api/v1/plugins/[^/]+/bridge$"),
    ("GET", r"^/api/v1/approvals/[^/]+$"),
    # Approvals on the go: the pending approvals this person may decide, with
    # their masked preview and offered decisions, and approve/reject of any of them (chat, workflow run, REST write).
    # The routes run the same decision checks as the web; "Always for this Workspace" stays in the web.
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
    """The phone id of an access token already verified by ``decode_token``; ``""`` for any other token."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return ""
    value = claims.get(ACCESS_CLAIM) if isinstance(claims, dict) else None
    return value if isinstance(value, str) else ""


def verified_phone_id(token: str, *, user_id: str) -> str:
    """The phone id of ``token`` only after its signature is verified and it belongs to ``user_id``; else ``""``.

    For any decision about a phone: a request may authenticate with a bearer token or an API key
    while carrying a forged access cookie, so the cookie's claims are never read unverified."""
    try:
        if decode_token(token, allow_phone=True) != user_id:
            return ""
    except HTTPException:  # any invalid token is no phone
        return ""
    return mobile_session_id(token)


def request_phone_id(request: Request, *, user_id: str) -> str:
    """The verified phone id of the phone's access cookie on ``request`` for ``user_id``, else ``""``.

    The phone's own ``octryx_phone_access`` cookie; a web token there names no phone."""
    return verified_phone_id(str(request.cookies.get(PHONE_ACCESS_COOKIE) or ""), user_id=user_id)


async def mobile_access_refusal(db: AsyncSession, token: str, *, user_id: str, method: str, path: str) -> str:
    """``""`` for a non-phone token, or a valid phone of ``user_id`` on a phone surface; else the fixed reason."""
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
