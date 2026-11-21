"""Fetch one public web document for Knowledge ingestion, safely (research packages).

Research proposes URLs from web search results, so every URL is untrusted. The fetch is closed:

- ``https`` only, default or explicit port 443, no credentials in the URL;
- the fetch goes through the pinned ``public_web`` client (``services/outbound_egress/public_web.py``)
  with its stricter address rule : the host is resolved **once** per request
  and redirect hop, every address must be globally routable (private, loopback, link-local,
  multicast, reserved, shared and documentation addresses are refused), and the connection goes
  only to the checked address, so a DNS answer that changes after the check (rebinding) is never
  connected. Environment proxies are never read; the admin-named web fetch proxy is used when one
  is configured;
- redirects are followed by hand, at most :data:`MAX_REDIRECTS`, and each hop is checked again;
- the body is bounded by the ingestion limits and read as a stream;
- the answer's content type decides the path: HTML and PDF go to the Docling sandbox, plain text,
  Markdown and AsciiDoc are text-native. Anything else is refused.

A refusal is a fixed reason token; no server text, header or body is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from ...outbound_egress.pinned_transport import EgressRefusedError
from ...outbound_egress.public_web import public_web_client
from ...outbound_url_policy import REASON_UNRESOLVABLE_HOST
from ..ingestion.text_ingest import MAX_TEXT_BYTES, MAX_UPLOAD_BYTES

MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "Octryx-Knowledge/1.0 (+research package fetch)"
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
# Content type -> (declared media type for ingestion, byte bound).
_MEDIA = {
    "text/html": ("text/html", MAX_UPLOAD_BYTES),
    "application/xhtml+xml": ("text/html", MAX_UPLOAD_BYTES),
    "application/pdf": ("application/pdf", MAX_UPLOAD_BYTES),
    "text/plain": ("text/plain", MAX_TEXT_BYTES),
    "text/markdown": ("text/markdown", MAX_TEXT_BYTES),
    "text/x-markdown": ("text/markdown", MAX_TEXT_BYTES),
    "text/asciidoc": ("text/asciidoc", MAX_TEXT_BYTES),
}


class FetchRefusedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    url: str
    media_type: str
    data: bytes


def _require_public_https(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise FetchRefusedError("not_public_https")
    try:
        port = parts.port or 443
    except ValueError:
        raise FetchRefusedError("not_public_https") from None
    if port != 443:
        raise FetchRefusedError("not_public_https")


def _client(network_backend: httpcore.AsyncNetworkBackend | None) -> httpx.AsyncClient:
    return public_web_client(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        network_backend=network_backend,
        globally_routable_only=True,
        follow_redirects=False,
    )


def _egress_refusal(refused: EgressRefusedError) -> FetchRefusedError:
    if refused.reason == REASON_UNRESOLVABLE_HOST:
        return FetchRefusedError("unresolvable")
    return FetchRefusedError("not_public_address")


def _media_of(content_type: str, url: str) -> tuple[str, int]:
    bare = content_type.split(";", 1)[0].strip().lower()
    if bare in ("text/plain", "application/octet-stream") and url.lower().endswith((".adoc", ".asciidoc")):
        bare = "text/asciidoc"
    if bare == "text/plain" and url.lower().endswith(".md"):
        bare = "text/markdown"
    if bare not in _MEDIA:
        raise FetchRefusedError("unsupported_content_type")
    return _MEDIA[bare]


async def fetch_public_document(
    url: str, *, network_backend: httpcore.AsyncNetworkBackend | None = None
) -> FetchedDocument:
    """GET one public document; follows at most :data:`MAX_REDIRECTS` checked redirects.

    ``network_backend`` replaces the socket layer under the pinned transport (a test seam for the
    connect address); it cannot skip the check.
    """
    current = url
    async with _client(network_backend) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _require_public_https(current)
            try:
                async with client.stream("GET", current) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchRefusedError("redirect_without_location")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise FetchRefusedError("status")
                    media_type, bound = _media_of(response.headers.get("content-type", ""), current)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > bound:
                            raise FetchRefusedError("too_large")
                    if not body:
                        raise FetchRefusedError("empty")
                    return FetchedDocument(url=current, media_type=media_type, data=bytes(body))
            except EgressRefusedError as refused:
                raise _egress_refusal(refused) from None
            except httpx.HTTPError:
                raise FetchRefusedError("transport") from None
    raise FetchRefusedError("too_many_redirects")


async def probe_public_document(url: str, *, network_backend: httpcore.AsyncNetworkBackend | None = None) -> str:
    """The media type ``url`` would be ingested as, reading only the headers; refuses like a fetch."""
    current = url
    async with _client(network_backend) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _require_public_https(current)
            try:
                async with client.stream("GET", current) as response:
                    if response.status_code in _REDIRECT_STATUSES and response.headers.get("location"):
                        current = urljoin(current, response.headers["location"])
                        continue
                    if response.status_code != 200:
                        raise FetchRefusedError("status")
                    return _media_of(response.headers.get("content-type", ""), current)[0]
            except EgressRefusedError as refused:
                raise _egress_refusal(refused) from None
            except httpx.HTTPError:
                raise FetchRefusedError("transport") from None
    raise FetchRefusedError("too_many_redirects")


__all__ = ["FetchRefusedError", "FetchedDocument", "MAX_REDIRECTS", "fetch_public_document", "probe_public_document"]
