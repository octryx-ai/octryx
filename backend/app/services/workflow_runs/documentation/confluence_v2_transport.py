"""The pinned Cloud v2 base and transport of ``confluence_v2``: status-code classification and cursor scans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

import httpx

from app.services.connector_auth.atlassian_modes import CONFLUENCE

from ....services.outbound_egress import CONNECTION_CONFLUENCE, egress_transport
from ....services.outbound_egress.pinned_transport import EgressRefusedError
from ....tools._confluence_instance import confluence_instance
from ...connector_auth.atlassian import auth_headers, request_auth
from .confluence_v2_errors import (
    KIND_CONFLICT,
    KIND_MALFORMED,
    KIND_NOT_FOUND,
    KIND_PERMISSION,
    KIND_REJECTED,
    KIND_TRANSPORT,
    KIND_UNAVAILABLE,
    SENT_NO,
    SENT_REFUSED,
    SENT_UNKNOWN,
    V2Error,
    V2ProfileRefusalError,
    _malformed,
)
from .confluence_v2_payloads import V2Scan

TIMEOUT_SECONDS = 30.0
MAX_SCAN_PAGES = 40  # 40 x 250 children; beyond that a scan is incomplete, never "absent"


_GATEWAY_PATH = re.compile(r"^(/ex/confluence/[A-Za-z0-9-]+)(/wiki)?$")
# Errors raised before any request byte left the client (or the egress refused it before sending).
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol,
                    httpx.InvalidURL, EgressRefusedError)


@dataclass(frozen=True, slots=True)
class V2Base:
    site: str
    api: str
    origin: str
    prefix: str


def api_base(instance: object) -> V2Base:
    normalized = confluence_instance(instance)
    if not normalized:
        raise V2ProfileRefusalError("the pinned Confluence instance is not an absolute http(s) URL")
    parts = urlsplit(normalized)
    host, path = (parts.hostname or "").lower(), parts.path
    if parts.scheme != "https":
        raise V2ProfileRefusalError(f"{normalized} is not https: the Cloud v2 profile needs an Atlassian Cloud site")
    origin = f"{parts.scheme}://{parts.netloc}"
    if host.endswith(".atlassian.net") and path in ("", "/wiki"):
        prefix = ""
    elif host == "api.atlassian.com" and (match := _GATEWAY_PATH.match(path)):
        prefix = match.group(1)
    else:
        raise V2ProfileRefusalError(
            f"{normalized} is not an Atlassian Cloud Confluence site; the publication adapter supports Confluence "
            "Cloud REST v2 only (Data Center is not supported) and never replaces a configured base path")
    site = f"{origin}{prefix}/wiki"
    return V2Base(site=site, api=f"{site}/api/v2", origin=origin, prefix=prefix)


def _link_next(response: httpx.Response) -> str | None:
    for part in response.headers.get_list("link") if hasattr(response.headers, "get_list") else []:
        for item in part.split(","):
            match = re.match(r'\s*<([^>]+)>\s*;\s*rel="?next"?', item)
            if match:
                return match.group(1)
    return None


class V2Transport:
    def __init__(self, instance: str, config: dict[str, Any], *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = TIMEOUT_SECONDS) -> None:
        from ....tools._confluence_access import normalize_page_rules

        if normalize_page_rules(config):
            raise V2ProfileRefusalError("the Cloud v2 publication profile cannot prove configured page/subtree "
                                        "allowlists without complete ancestors; no request is made")
        self.base = api_base(instance)
        self._config = config
        self._transport = transport
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        headers = {"Accept": "application/json", **auth_headers(CONFLUENCE, self._config)}
        self._client = httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, headers=headers,
            transport=self._transport or egress_transport(CONNECTION_CONFLUENCE),
            auth=request_auth(CONFLUENCE, self._config))
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _send(self, method: str, url: str, *, params: dict[str, Any] | None = None,
                    json: dict[str, Any] | None = None, mutating: bool = False) -> httpx.Response:
        assert self._client is not None, "use CloudV2Client as an async context manager"
        try:
            response = await self._client.request(method, url, params=params, json=json)
        except _NOT_SENT_ERRORS as error:
            raise V2Error(KIND_TRANSPORT, f"{type(error).__name__}: the request was not sent", sent=SENT_NO) from None
        except httpx.HTTPError as error:
            raise V2Error(KIND_TRANSPORT, f"{type(error).__name__}: no answer",
                          sent=SENT_UNKNOWN if mutating else SENT_NO) from None
        code = response.status_code
        if 200 <= code < 300:
            return response
        # Classified by the status code alone; the body is never matched.
        if 300 <= code < 400:
            raise V2Error(KIND_MALFORMED, f"HTTP {code}: redirects are not followed (pinned base)",
                          status_code=code, sent=SENT_UNKNOWN if mutating else SENT_NO)
        if code == 409:
            kind = KIND_CONFLICT
        elif code in (401, 403):
            kind = KIND_PERMISSION
        elif code == 404:
            kind = KIND_NOT_FOUND
        elif code < 500 and code not in (408, 425, 429):
            kind = KIND_REJECTED
        else:
            kind = KIND_UNAVAILABLE
        sent = SENT_NO
        if mutating:
            sent = SENT_REFUSED if code in (400, 401, 403, 404, 405, 409, 410, 413, 414, 415, 422) else SENT_UNKNOWN
        raise V2Error(kind, f"HTTP {code}", status_code=code, sent=sent)

    async def _json(self, method: str, url: str, *, params: dict[str, Any] | None = None,
                    json: dict[str, Any] | None = None, mutating: bool = False) -> tuple[Any, httpx.Response]:
        response = await self._send(method, url, params=params, json=json, mutating=mutating)
        try:
            return response.json(), response
        except ValueError:
            raise _malformed("the body is not JSON", sent=SENT_UNKNOWN if mutating else SENT_NO) from None

    def _next_url(self, payload: dict[str, Any], response: httpx.Response, endpoint: str) -> str | None:
        links = payload.get("_links")
        if links is not None and not isinstance(links, dict):
            raise _malformed("_links is not an object")
        body_next = (links or {}).get("next")
        header_next = _link_next(response)
        if body_next is not None and not isinstance(body_next, str):
            raise _malformed("_links.next is not a link")
        if body_next and header_next and body_next != header_next:
            raise _malformed("the body and the Link header name different next pages")
        target = body_next or header_next
        if not target:
            return None
        parts = urlsplit(target)
        if parts.scheme or parts.netloc:
            if f"{parts.scheme}://{parts.netloc}" != self.base.origin:
                raise _malformed("the next link leaves the pinned site")
        path = parts.path
        if not path.startswith(self.base.prefix + "/wiki/api/v2/"):
            if self.base.prefix and path.startswith("/wiki/api/v2/"):
                path = self.base.prefix + path  # gateway links are relative to the site prefix
            else:
                raise _malformed("the next link is not on the pinned REST v2 base")
        if path != urlsplit(endpoint).path:
            raise _malformed("the next link names another endpoint")
        if not parse_qs(parts.query).get("cursor"):
            raise _malformed("the next link carries no cursor")
        return f"{self.base.origin}{path}?{parts.query}"

    async def _scan(self, endpoint: str, params: dict[str, Any], parse) -> V2Scan:
        items: list[Any] = []
        url, query, seen = endpoint, dict(params), set()
        for read in range(1, MAX_SCAN_PAGES + 1):
            try:
                payload, response = await self._json("GET", url, params=query)
                if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                    raise _malformed("results is not a list")
                items.extend(parse(item) for item in payload["results"])
                following = self._next_url(payload, response, endpoint)
            except V2Error as error:
                return V2Scan(tuple(items), False, f"{error.kind}: {error}", read)
            if following is None:
                return V2Scan(tuple(items), True, "", read)
            if following in seen:
                return V2Scan(tuple(items), False, "malformed: the cursor repeats", read)
            seen.add(following)
            url, query = following, None
        return V2Scan(tuple(items), False, f"scan cap of {MAX_SCAN_PAGES} pages reached", MAX_SCAN_PAGES)
