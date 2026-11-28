"""The pet's one platform read with an ETag; :func:`fetch` never raises and never reads failed bodies.
A 401 is retried once with a fresh token because the Windows bridge may cache a stale one."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from ..platform import CONTROL_PLANE_PREFIX, HEADER_REASON, HEADER_STATE, safe_code
from ..tokens import TokenUnavailableError
from .account import Account
from .model import PetState, parse

PATH = "/pet"
TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class FetchResult:
    outcome: str  # ok | not_modified | signed_out | refused | unreachable
    pet: PetState | None = None
    etag: str = ""
    status_code: int = 0
    reason: str = ""


def resolve(base: str, link: str | None) -> str | None:
    if not link or not base:
        return None
    url = urljoin(base + "/", link)
    return url if urlsplit(url).scheme in ("http", "https") and urlsplit(url).netloc else None


def _get(account: Account, http: httpx.Client, url: str, headers: dict[str, str], params, *,
         refresh: bool) -> httpx.Response | FetchResult:
    try:
        token = account.token(http, refresh=refresh)
    except TokenUnavailableError as exc:
        return FetchResult("signed_out", reason=safe_code(exc.code))
    try:
        return http.get(url, headers={**headers, "Authorization": f"Bearer {token}"}, params=params,
                        timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return FetchResult("unreachable", reason="platform_unreachable")


def fetch(account: Account, *, http: httpx.Client, etag: str = "", project_id: str = "") -> FetchResult:
    base = account.base_url()
    if not base:
        return FetchResult("signed_out", reason="not_configured")
    url = f"{base}{CONTROL_PLANE_PREFIX}{PATH}"
    headers = {"If-None-Match": etag} if etag else {}
    params = {"project_id": project_id} if project_id else None
    response = _get(account, http, url, headers, params, refresh=False)
    if isinstance(response, httpx.Response) and response.status_code == 401:
        response = _get(account, http, url, headers, params, refresh=True)
    if isinstance(response, FetchResult):
        return response
    if response.status_code == 304:
        return FetchResult("not_modified", etag=etag, status_code=304)
    if response.status_code == 401:
        return FetchResult("signed_out", status_code=401, reason=safe_code(response.headers.get(HEADER_REASON)))
    if response.status_code >= 500:
        return FetchResult("unreachable", status_code=response.status_code, reason="platform_error")
    if response.status_code != 200:
        reason = safe_code(response.headers.get(HEADER_REASON)) or safe_code(response.headers.get(HEADER_STATE))
        return FetchResult("refused", status_code=response.status_code, reason=reason)
    try:
        body = response.json()
    except ValueError:
        return FetchResult("unreachable", status_code=200, reason="invalid_response")
    if not isinstance(body, dict):
        return FetchResult("unreachable", status_code=200, reason="invalid_response")
    return FetchResult("ok", pet=parse(body), etag=str(response.headers.get("etag") or "")[:200], status_code=200)


__all__ = ["FetchResult", "fetch", "resolve"]
