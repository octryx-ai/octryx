"""Same-origin policy for cookie-authenticated admin-panel mutations.

The admin panel authenticates from an ``HttpOnly`` auth cookie. ``SameSite=lax``
(:mod:`app.auth_cookie_policy`) already stops the simplest cross-site POST, but
it is one browser-side setting: it does not cover a same-site subdomain, a
deployment that has to relax ``SameSite`` for an embedded surface, or a browser
that does not apply it. This module is the additive, server-side half — it does
not change, and must not be used to justify relaxing, the cookie attributes.

What it decides, for one request:

* **Is this a guarded surface?** Only paths containing ``/chat/api/panel/``. The
  marker is matched anywhere in the path because the panel routers are mounted
  twice — under ``/admin`` and, for the approvals/budget/exec-policy group, at
  the root — and both mounts must be covered by the same rule.
* **Is this a cookie-authenticated browser mutation?** Safe methods are never
  state-changing. Beyond that the question is decided by the credential the
  guarded routes actually authenticate with, in their order, not by whichever
  header the caller chose to attach:
  :func:`app.web._helpers.cookie_principal.principal_id_from_request` reads the
  auth cookie first and only falls back to a bearer token. So **an auth cookie
  wins**: a request carrying it is authenticated by it, and must prove its
  origin even when it also carries ``Authorization: Bearer ...`` or
  ``X-API-Key: ...``. Those headers are attacker-controllable — a cross-site
  page cannot read the victim's token, but it can send an arbitrary or empty
  value — so treating their mere presence as an exemption would hand the
  attacker the bypass. Only a request with **no** auth cookie may be exempt, and
  then only for a bearer token, which is the one credential this surface
  authenticates that a cross-site page cannot attach by itself. ``X-API-Key`` is
  deliberately **not** an exemption here: the web surface never authenticates an
  API key (``principal_id_from_request`` decodes a JWT), so such a request has no
  credential on this surface and is simply left to the route's own 401 — the same
  outcome as any other request with no auth cookie.
* **Does its origin match?** ``Origin`` is authoritative when present; browsers
  send it on every non-``GET``/``HEAD`` request. ``Referer`` is the documented
  fallback for the few clients that strip ``Origin``. When neither is present the
  request is refused rather than admitted: a request that carries an ambient
  cookie but declines to say where it came from cannot be told apart from a
  forged one, so the bounded behavior is deny.

Where the expected origin comes from — and where it deliberately does not:

* The effective request origin (:func:`app.http_security.current_request_origin`)
  built from the scheme the validated trusted-proxy boundary resolved and
  the request's own ``Host``. ``X-Forwarded-Host`` is never applied anywhere in
  this application, and ``X-Forwarded-Proto``/``Forwarded`` are only read for a
  peer in ``trusted_proxy_ips``; a forged forwarded header therefore cannot move
  the expected origin. Nothing here parses a forwarded header itself.
* ``cors_allowed_origins``, the same explicit allowlist that already lets those
  origins send credentialed cross-origin requests. It is deployment
  configuration, not inference, so a split-origin deployment stays supported
  without a second list to keep in sync.

A refusal is one fixed 403 with no request-derived content: the same answer for
an existing and a non-existent resource, on this Workspace or another.

Deployment note: the expected origin is HTTPS only when the runtime knows the
request was HTTPS. Behind a TLS-terminating ingress that means
``trusted_proxy_ips`` must name the ingress, which is the same
requirement the ``Secure`` cookie attribute already depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Request

from .auth_cookie_policy import ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE
from .config import Settings, get_settings
from .http_security import (
    SAFE_HTTP_METHODS,
    current_request_origin,
    parse_cors_allowed_origins,
)

#: Every guarded path contains this marker, under any mount prefix.
PANEL_PATH_MARKER = "/chat/api/panel/"

#: Cookies that authenticate a browser on the panel surface.
PANEL_AUTH_COOKIES = (ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE)

CSRF_REJECTION_STATUS = 403
CSRF_REJECTION_DETAIL = "Cross-site request blocked."

# Allow reasons.
REASON_SAFE_METHOD = "safe_method"
REASON_UNGUARDED_PATH = "unguarded_path"
#: No auth cookie, but a bearer token — the credential this surface falls back to
#: and the one a cross-site page cannot attach.
REASON_BEARER_CLIENT = "bearer_client"
#: No auth cookie and no bearer token: nothing this surface authenticates with,
#: so the route answers 401 on its own.
REASON_NO_AUTH_COOKIE = "no_auth_cookie"
REASON_EFFECTIVE_ORIGIN = "effective_request_origin"
REASON_CONFIGURED_ORIGIN = "configured_allowed_origin"

# Deny reasons.
REASON_FOREIGN_ORIGIN = "foreign_origin"
REASON_MISSING_ORIGIN = "missing_origin_evidence"

__all__ = [
    "CSRF_REJECTION_DETAIL",
    "CSRF_REJECTION_STATUS",
    "PANEL_AUTH_COOKIES",
    "PANEL_PATH_MARKER",
    "REASON_BEARER_CLIENT",
    "REASON_CONFIGURED_ORIGIN",
    "REASON_EFFECTIVE_ORIGIN",
    "REASON_FOREIGN_ORIGIN",
    "REASON_MISSING_ORIGIN",
    "REASON_NO_AUTH_COOKIE",
    "REASON_SAFE_METHOD",
    "REASON_UNGUARDED_PATH",
    "OriginDecision",
    "evaluate_panel_mutation",
    "expected_panel_origins",
    "is_guarded_panel_path",
]


@dataclass(frozen=True)
class OriginDecision:
    """Outcome of the policy for one request.

    ``reason`` is an enum-like constant. It never contains a header value, a
    path, a cookie or an address, so it is safe to log.
    """

    allowed: bool
    reason: str


def is_guarded_panel_path(path: str | None) -> bool:
    """True for a panel path under any mount prefix.

    ``root_path`` is irrelevant: the marker is matched as a substring, so the
    decision is the same whether the application is mounted at ``/`` or deeper.
    """
    return PANEL_PATH_MARKER in str(path or "")


def _normalize_origin(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _has_bearer_authorization(request: Request) -> bool:
    authorization = str(request.headers.get("authorization") or "").strip()
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and bool(token.strip())


def _has_panel_auth_cookie(request: Request) -> bool:
    return any(str(request.cookies.get(name) or "").strip() for name in PANEL_AUTH_COOKIES)


def _resolve_claimed_origin(request: Request) -> str:
    """Origin the request claims to come from, or ``""`` when it claims none.

    ``Referer`` is only consulted when no ``Origin`` header was sent at all. An
    ``Origin`` that is present but not a usable origin — ``null`` from a
    sandboxed or privacy-stripped context — is a claim the policy cannot match,
    not a missing one, so it is never rescued by a ``Referer``.
    """
    if "origin" in request.headers:
        return _normalize_origin(request.headers.get("origin"))
    return _normalize_origin(request.headers.get("referer"))


def expected_panel_origins(request: Request, settings: Settings | None = None) -> tuple[str, ...]:
    """Origins a cookie-authenticated panel mutation may come from.

    The effective request origin first, then the configured CORS allowlist. Both
    are normalized to ``scheme://host[:port]``.
    """
    resolved = settings or get_settings()
    origins = [current_request_origin(request)]
    for origin in parse_cors_allowed_origins(resolved.cors_allowed_origins):
        if origin not in origins:
            origins.append(origin)
    return tuple(origin for origin in origins if origin)


def _decide_by_origin(request: Request, settings: Settings | None) -> OriginDecision:
    origin = _resolve_claimed_origin(request)
    if not origin:
        return OriginDecision(False, REASON_MISSING_ORIGIN)
    expected = expected_panel_origins(request, settings)
    if expected and origin == expected[0]:
        return OriginDecision(True, REASON_EFFECTIVE_ORIGIN)
    if origin in expected:
        return OriginDecision(True, REASON_CONFIGURED_ORIGIN)
    return OriginDecision(False, REASON_FOREIGN_ORIGIN)


def evaluate_panel_mutation(request: Request, settings: Settings | None = None) -> OriginDecision:
    """Apply the policy to *request*; see the module docstring for the rules.

    The credential branches are ordered exactly like the resolver the guarded
    routes use: cookie, then bearer. An attacker-supplied ``Authorization`` or
    ``X-API-Key`` header therefore cannot exempt a request that the route would
    still authenticate from the ambient cookie.
    """
    if not is_guarded_panel_path(request.url.path):
        return OriginDecision(True, REASON_UNGUARDED_PATH)
    if request.method.upper() in SAFE_HTTP_METHODS:
        return OriginDecision(True, REASON_SAFE_METHOD)
    if _has_panel_auth_cookie(request):
        return _decide_by_origin(request, settings)
    if _has_bearer_authorization(request):
        return OriginDecision(True, REASON_BEARER_CLIENT)
    return OriginDecision(True, REASON_NO_AUTH_COOKIE)
