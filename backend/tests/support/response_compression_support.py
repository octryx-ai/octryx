"""Shared helpers for the test_response_compression_* modules."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers

from app.web.static_files import clear_compressed_cache

IDENTITY = {"accept-encoding": "identity"}


GZIP = {"accept-encoding": "gzip, deflate, br"}


def _raw_client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", headers=IDENTITY)


async def _wire(client: AsyncClient, method: str, path: str, headers: dict[str, str]) -> tuple[int, Headers, bytes]:
    async with client.stream(method, path, headers=headers) as response:
        body = b"".join([chunk async for chunk in response.aiter_raw()])
        return response.status_code, Headers(raw=response.headers.raw), body


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_compressed_cache()
    yield
    clear_compressed_cache()
