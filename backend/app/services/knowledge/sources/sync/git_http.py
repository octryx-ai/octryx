"""Read-only HTTPS reads of a Git host for the ``git_repository`` connector. A host gets exactly its connection's
credential, never another one."""

from __future__ import annotations

import json

import httpx

from ....outbound_egress import CONNECTION_GIT_REPOSITORY, EgressRefusedError, egress_transport
from .contract import (
    REASON_EGRESS_REFUSED,
    REASON_REPOSITORY_TOO_LARGE,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_UNAVAILABLE,
    ConnectorError,
)
from .git_hosts import SHA
from .http import reason_for_status

DEFAULT_TIMEOUT_SECONDS = 60.0
_HEADERS = {"User-Agent": "Octryx-SourceSync"}
_COMMIT_SHA_MEDIA_TYPE = "application/vnd.github.sha"
_MAX_COMMIT_ANSWER_BYTES = 200
_MAX_COMMIT_JSON_BYTES = 256 * 1024
_REDIRECTS = (301, 302, 303, 307, 308)


class HostStatusError(ConnectorError):
    def __init__(self, status: int) -> None:
        super().__init__(reason_for_status(status))
        self.status = status


class GitHostReader:
    def __init__(
        self, *, transport: httpx.AsyncBaseTransport | None = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        auth: tuple[str, str] | None = None, bearer: str | None = None, bearer_host: str = "api.github.com",
    ) -> None:
        self._transport = transport
        self._timeout = timeout_seconds
        self._auth = auth
        self._bearer = bearer
        self._bearer_host = bearer_host

    def _client(self) -> httpx.AsyncClient:
        transport = egress_transport(CONNECTION_GIT_REPOSITORY, inner=self._transport)
        return httpx.AsyncClient(transport=transport, timeout=self._timeout, follow_redirects=False, auth=self._auth)

    async def resolve_commit(self, url: str, *, json_key: str = "") -> str:
        if json_key:
            body = await self._get(url, accept="application/json", max_bytes=_MAX_COMMIT_JSON_BYTES)
            try:
                value = json.loads(body).get(json_key)
            except (ValueError, AttributeError):
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
            body = str(value or "").encode("ascii", "replace")
        else:
            body = await self._get(url, accept=_COMMIT_SHA_MEDIA_TYPE, max_bytes=_MAX_COMMIT_ANSWER_BYTES)
        try:
            sha = body.decode("ascii").strip().lower()
        except UnicodeDecodeError:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
        if not SHA.fullmatch(sha):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return sha

    async def archive(self, url: str, *, max_bytes: int, redirect_host: str | None = None) -> bytes:
        if redirect_host is None:
            return await self._get(url, accept="application/gzip", max_bytes=max_bytes)
        # The token goes to ``bearer_host`` only (``_headers``), so the redirect target is fetched without it.
        target = await self._redirect(url, host=redirect_host)
        return await self._get(target, accept="application/gzip", max_bytes=max_bytes)

    async def _redirect(self, url: str, *, host: str) -> str:
        try:
            async with self._client() as client:
                response = await client.get(url, headers=self._headers(url, "application/vnd.github+json"))
        except EgressRefusedError:
            raise ConnectorError(REASON_EGRESS_REFUSED) from None
        except httpx.HTTPError:
            raise ConnectorError(REASON_SOURCE_UNAVAILABLE) from None
        if response.status_code == 200:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)  # an archive must arrive by its redirect
        if response.status_code not in _REDIRECTS:
            raise HostStatusError(response.status_code)
        try:
            target = httpx.URL(response.headers.get("location") or "")
        except httpx.InvalidURL:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
        if target.scheme != "https" or target.host != host or target.port is not None or target.userinfo:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return str(target)

    async def json(self, url: str, *, max_bytes: int) -> object:
        body = await self._get(url, accept="application/vnd.github+json", max_bytes=max_bytes)
        try:
            return json.loads(body)
        except ValueError:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None

    def _headers(self, url: str, accept: str) -> dict[str, str]:
        headers = {**_HEADERS, "Accept": accept}
        if self._bearer and httpx.URL(url).host == self._bearer_host:
            headers["Authorization"] = f"Bearer {self._bearer}"
        return headers

    async def _get(self, url: str, *, accept: str, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        size = 0
        try:
            async with self._client() as client:
                async with client.stream("GET", url, headers=self._headers(url, accept)) as response:
                    if response.status_code != 200:
                        raise HostStatusError(response.status_code)
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ConnectorError(REASON_REPOSITORY_TOO_LARGE)
                        chunks.append(chunk)
        except EgressRefusedError:
            raise ConnectorError(REASON_EGRESS_REFUSED) from None
        except httpx.HTTPError:
            raise ConnectorError(REASON_SOURCE_UNAVAILABLE) from None
        return b"".join(chunks)


__all__ = ["GitHostReader", "HostStatusError"]
